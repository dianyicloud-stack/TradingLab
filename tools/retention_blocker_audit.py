"""Readonly production evidence; never initializes production repositories."""
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
import json,sqlite3,urllib.request,sys,os,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from bridges.market_agent import AgentClient
def main():
    out=ROOT/'artifacts/retention_blockers';out.mkdir(exist_ok=True)
    config=json.loads((ROOT/'data/system/market-source.json').read_text(encoding='utf-8'))['config'];root=Path(config['market_agent_root'])
    report={'at':datetime.now(timezone.utc).isoformat(),'configuration':config,'http':{}}
    for p in ('/healthz','/api/live/runtime-version','/api/live/advisory/settings','/api/live/stocks','/api/system/maintenance'):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765'+p,timeout=10) as f:v=json.load(f)
            if p.endswith('stocks'):v={k:v.get(k) for k in ('listener_state','source_owner','source_generation','ai_tasks')}
            report['http'][p]=v
        except Exception as e:report['http'][p]={'error':type(e).__name__}
    try:
        q=AgentClient(root).query();report['agent']={k:q.get(k) for k in ('agent_identity','build_id','capabilities','source','status','agent_state','last_cycle_at','errors')}
    except Exception as e:report['agent']={'error':type(e).__name__}
    with closing(sqlite3.connect((root/'market_agent.db').as_uri()+'?mode=ro',uri=True)) as db:
        report['readiness']=db.execute('select day,payload from retention_readiness').fetchall()
        state=json.loads(db.execute('select state from checkpoint where id=1').fetchone()[0])
        report['checkpoint_keys']=list(state);report['sessions']=[{'symbol':s['symbol'],'date':s['date'],'rows':len(s.get('rows',[]))} for s in state.get('store',{}).get('sessions',{}).values()]
        report['watchlist']=[{k:w.get(k) for k in ('symbol','lifecycle_status','tracking_session_id')} for w in state.get('store',{}).get('watchlist',[])]
        # Consistent isolated copy for upgrade tests. Source connection is mode=ro.
        dest=out/'production-copy';dest.mkdir(exist_ok=True)
        with closing(sqlite3.connect(dest/'market_agent.db')) as target:db.backup(target)
    p=ROOT/'tests/ui-stability-6t0th4yw';st=p.stat(follow_symlinks=False)
    report['directory']={'path':str(p),'resolved':str(p.resolve()),'attributes':getattr(st,'st_file_attributes',0),'reparse':bool(getattr(st,'st_file_attributes',0)&1024)}
    try:report['directory']['children']=[x.name for x in p.iterdir()];report['directory']['access']='READABLE_NOW'
    except OSError as e:report['directory'].update(access='ERROR',error=type(e).__name__,winerror=getattr(e,'winerror',None))
    with closing(sqlite3.connect((ROOT/'data/runtime/live/advisory/advisory_runtime.db').as_uri()+'?mode=ro',uri=True)) as db:
        report['tasks']=db.execute('select status,count(*) from live_analysis_requests group by status').fetchall()
        report['settings_hashes']={}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if any(word in name for word in ('settings','preferences','cursor','retired')):
                report['settings_hashes'][name]=hashlib.sha256(json.dumps(db.execute('SELECT * FROM "'+name+'"').fetchall(),sort_keys=True,default=str).encode()).hexdigest()
    report['account_modes']=[]
    for p in (ROOT/'data/account/unified').glob('AC-*/account.db'):
        with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as db:
            body=json.loads(db.execute('SELECT body FROM projection').fetchone()[0]);report['account_modes'].append({'id':p.parent.name,'type':body['account_type'],'mode':body['policy']['ai_execution_mode']})
    report['artifact_registry_exists']=(ROOT/'artifacts/maintenance-registry.json').exists()
    (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('at','agent','directory','tasks','artifact_registry_exists')},ensure_ascii=False))
if __name__=='__main__':main()
