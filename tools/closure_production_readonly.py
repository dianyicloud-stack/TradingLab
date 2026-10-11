"""Read-only live sampling; never builds the application or opens owner databases."""
from pathlib import Path
from datetime import datetime,timezone
import json,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adapters.source_configuration import source_configuration
from bridges.market_agent import AgentClient,AgentFactBridge
from bridges.active_market_source import ActiveMarketSource
from engines.live.qualification import validate

def main():
    out=ROOT/'artifacts/m2_auto_agent_closure';_,config=source_configuration(ROOT,ROOT/'data')
    client=AgentClient(config['market_agent_root']);bridge=AgentFactBridge(client);source=ActiveMarketSource(bridge,config)
    web={'status':'UNAVAILABLE','instance_id':None}
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=2) as response:
            health=json.load(response);web={'status':health.get('status'),'instance_id':health.get('instance_id')}
        with urllib.request.urlopen('http://127.0.0.1:8765/api/live/runtime-version',timeout=3) as response:
            version=json.load(response);web['build_id']=version.get('build_id')
    except (OSError,ValueError):pass
    rows=[]
    with source.read_scope():
        value=client.query()
        seen=set()
        for session in bridge.sessions():
            if session.get('lifecycle') not in ('ACTIVE','TRACKED') or session['symbol'] in seen:continue
            seen.add(session['symbol'])
            facts=bridge.advisory_facts(session['symbol']);checks=[]
            session=facts['session']
            for event in facts['events'][-5:]:
                check=validate(event,facts['observations'],facts['session'])
                checks.append({k:check[k] for k in ('event_id','event_type','status','missing')})
            rows.append({'symbol':session['symbol'],'session':session['tracking_session_id'],
                'owner':session.get('source_owner'),'source_watermark':session.get('source_watermark'),'events_checked':checks})
    old=ROOT.parent/'TradingLabData/V2AWorkspace';identity=value.get('agent_identity',{})
    status={'at':datetime.now(timezone.utc).isoformat(),'web':web,'agent':{'pid':identity.get('pid'),
        'state':value['agent_state'],'build':identity.get('build_version'),
        'root':str(client.root),'tracked':[r['symbol'] for r in rows],'errors':[{'code':e.get('code')} for e in value.get('errors',[])]},
        'configured_source':config['active_market_source'],'agent_auto_start':config['agent_auto_start'],
        'generation':config['source_generation'],'ignored_keys':config.get('deprecated_ignored',[]),
        'workspace_is_junction':old.is_junction(),'workspace_resolved':str(old.resolve()),'workspace_exists':old.exists()}
    (out/'current-production-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'current-owner-readonly-validation.json').write_text(json.dumps({'at':status['at'],
        'note':'Only GET Agent Contract and pure bridge/evidence validation; no repository initialization, task, Provider or cursor mutation. Not full eligibility age/settings.',
        'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
if __name__=='__main__':main()
