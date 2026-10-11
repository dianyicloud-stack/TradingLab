"""Production snapshot -> isolated native owner; fixture Kline transport, no network."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from datetime import datetime
from unittest.mock import patch
import json,sys,sqlite3,subprocess,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engines.live.market_agent.service import AgentService
from engines.live.market_agent.retention import AgentRetention
from engines.account.rules import TradingCalendar
def main():
    out=ROOT/'artifacts/retention_blockers';source=out/'production-copy/market_agent.db'
    with TemporaryDirectory(dir=ROOT/'tests',prefix='real-shape-upgrade-') as temp:
        root=Path(temp)
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(root/'market_agent.db')) as new:
            old.backup(new);state=json.loads(old.execute('select state from checkpoint').fetchone()[0]);day=max(s['date'] for s in state['store']['sessions'].values())
        now=datetime.fromisoformat(day+'T15:20:00+08:00');cal=TradingCalendar();s=AgentService(root,source='USER',network=False,clock=lambda:now,calendar=cal.is_open)
        result={'production_snapshot_only':True,'isolated_day':day,'real_network':False,'startup_validation':AgentRetention(s).validation(),'startup_plan_blocked':AgentRetention(s).plan()['blocked']}
        before=s.repo.facts();s.close();original=subprocess.Popen
        def fixture(args,*a,**kw):
            args=list(args)
            if str(args[1]).endswith('worker.mjs'):args[1]=str(ROOT/'tests/retention_worker_fixture.mjs')
            return original(args,*a,**kw)
        with patch('engines.live.market_agent.service.subprocess.Popen',side_effect=fixture):s=AgentService(root,source='USER',clock=lambda:now,calendar=cal.is_open)
        try:
            result['validation']=s.command({'schema_version':'1.0','source':'USER','action':'RETENTION_VALIDATE','confirmation':'VALIDATE_NATIVE_BASELINES'})
            result['plan']=s.command({'schema_version':'1.0','source':'USER','action':'RETENTION_PREVIEW'});result['plan'].pop('rows',None)
            result['facts_unchanged']=before==s.repo.facts();result['status']='PASS' if result['validation']['status']=='PASSED' and not result['plan']['blocked'] and result['facts_unchanged'] else 'FAIL'
            (out/'production-shape-repro.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'status':result['status'],'missing_before':result['startup_validation']['missing'],'ranges_after':result['validation'].get('ranges'),'candidate_records':result['plan'].get('records'),'facts_unchanged':result['facts_unchanged']},ensure_ascii=False))
        finally:s.close()
if __name__=='__main__':main()
