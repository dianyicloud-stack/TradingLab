"""Five trading-day capacity run, 3 stocks x 2880 snapshots/day, isolated owner."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from tempfile import TemporaryDirectory
from contextlib import closing
import sys,json,sqlite3,uuid,copy,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engines.live.market_agent.service import AgentService
from engines.live.market_agent.retention import AgentRetention
from engines.account.rules import TradingCalendar
from tests.test_market_agent import frame

def main():
    out=ROOT/'artifacts/lifecycle_20260921';report={'source':'TEST','provider_calls':0,'records_per_day':8640,'days':[]}
    config=json.loads((ROOT/'data/system/market-source.json').read_text(encoding='utf-8'))['config'];source=Path(config['market_agent_root'])/'market_agent.db'
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
        sample=json.loads(db.execute("select payload from facts where kind='SNAPSHOT' order by seq desc limit 1").fetchone()[0])['sample']
    with TemporaryDirectory(dir=ROOT/'tests',prefix='lifecycle-capacity-') as tmp:
        root=Path(tmp);now=[datetime.fromisoformat('2026-09-14T09:35:40+08:00')];s=AgentService(root,clock=lambda:now[0],calendar=TradingCalendar().is_open)
        def cmd(action,symbol):return s.command({'schema_version':'1.0','source':'TEST','command_id':uuid.uuid4().hex,'expected_version':s.repo.command_version(),'action':action,'symbol':symbol,'name':'隔离容量测试','board':{'code':'BKTEST','name':'测试'}})
        symbols=['bj920161','sh688601','sz300474']
        for symbol in symbols:cmd('ADD',symbol)
        try:
            for n in range(5):
                now[0]=datetime.fromisoformat(f'2026-09-{14+n}T09:35:40+08:00');day=now[0].date().isoformat()
                frames={}
                for symbol in symbols:
                    cmd('BOARD',symbol);frames[symbol]=frame(now[0]);frames[symbol]['dataset']['volumeHistoryBars']=[{'date':(now[0].date()-timedelta(days=i)).isoformat(),'time':'09:35:00','volume':1000+i,'close':10} for i in range(1,31)]
                s.cycle(frames);assert not s.errors,s.errors
                state=s.repo.checkpoint()[1];sessions={x['symbol']:x['tracking_session_id'] for x in state['store']['sessions'].values() if x['date']==day}
                records=[]
                for symbol in symbols:
                    for i in range(2880):
                        start=datetime.fromisoformat(day+('T09:30:00+08:00' if i<1440 else 'T13:00:00+08:00'));at=(start+timedelta(seconds=(i%1440)*5)).isoformat()
                        value={**sample,'symbol':symbol,'name':'隔离容量测试','timestamp':at,'source_updated_at':at,'trade_source_captured_at':at}
                        records.append(('SNAPSHOT',sessions[symbol]+':TEST:'+str(i),{'tracking_session_id':sessions[symbol],'session_date':day,'sample':value}))
                now[0]=datetime.fromisoformat(day+'T15:00:00+08:00');s.repo.commit(state,records)
                before=s.repo.path.stat().st_size;plan=AgentRetention(s).plan();assert not plan['blocked'],plan
                command={'schema_version':'1.0','source':'TEST','keep_day':day,'run_id':'retain-'+day,'confirmation':'OWNER_RETENTION_V1'}
                s.command({**command,'action':'RETENTION_BACKUP'});started=time.monotonic();count=0;steps=0
                while True:
                    r=s.command({**command,'action':'RETENTION_APPLY'});steps+=1;count+=r.get('logical_records_deleted',0)
                    if r['status']=='DONE':break
                with s.repo.connect() as db:
                    size=db.execute('PRAGMA page_size').fetchone()[0];free=db.execute('PRAGMA freelist_count').fetchone()[0]*size;remaining=db.execute('select count(*) from facts').fetchone()[0]
                report['days'].append({'trading_day':day,'before_main_bytes':before,'after_main_bytes':s.repo.path.stat().st_size,'reusable_bytes':free,'records_deleted':count,'logical_payload_deleted_estimate':plan['estimated_logical_bytes'],'remaining_records':remaining,'actual_main_file_released_bytes':before-s.repo.path.stat().st_size,'backup_bytes':sum(p.stat().st_size for p in (root/'maintenance-backups').glob('*/*')),'batches':steps,'seconds':round(time.monotonic()-started,3)})
                (out/'capacity-trend.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            report['status']='PASS';assert max(x['remaining_records'] for x in report['days'])-min(x['remaining_records'] for x in report['days'])<20
            (out/'capacity-trend.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report))
        finally:s.close()
if __name__=='__main__':main()
