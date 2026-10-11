import copy,json,tempfile,time,unittest
from pathlib import Path
from datetime import datetime,timedelta,date
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from engines.history.bars import BarsEngine,TZ,normalize,aggregate,volume_context
from engines.history.store import HistoryStore
from engines.history.service import HistoricalAnalysis,evidence,PROMPT,SCHEMA
from engines.account.rules import TradingCalendar
from contracts.history.bars import HistoryError,request

class Adapter:
    source='TEST_SINA';maximum=1970
    def __init__(self,rows):self.rows=rows;self.calls=0
    def fetch(self,symbol,count):self.calls+=1;time.sleep(.01);return copy.deepcopy(self.rows[-count:])
class Provider:
    def __init__(self):self.inputs=[]
    def catalog(self):return {'default_provider':'fake','default_model':'fake'}
    def analyze_history(self,frozen,*args):
        self.inputs.append(frozen)
        return {'analysis':{'conclusion':'测试历史意见','basis':'来自截止日数据','next_observation':'观察后续量价','limitations':'样本有限'}}
def rows():
    out=[];d=date(2025,1,1);cal=TradingCalendar()
    while d<=date(2026,9,24):
        if cal.is_open(d.isoformat()):out.append(dict(day=d.isoformat(),open='10',high='12',low='9',close='11',volume=str(1000+len(out))))
        d+=timedelta(days=1)
    return out

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='history-test-');self.root=Path(self.temp.name);self.store=HistoryStore(self.root)
        self.now=datetime(2026,9,25,16,tzinfo=TZ);self.adapter=Adapter(rows());self.engine=BarsEngine(self.store,self.adapter,TradingCalendar(),lambda:self.now)
        self.q=dict(symbol='bj920161',end_date='2026-09-23',period='DAY',volume_period='WEEK',samples=20,limit=31,adjustment='NONE')
    def tearDown(self):self.temp.cleanup()
    def test_cutoff_and_deterministic_aggregation(self):
        a=self.engine.read(self.q);b=self.engine.read(self.q);self.assertEqual(a,b);self.assertTrue(all(x['date']<='2026-09-23' for x in a['bars']))
        w=self.engine.read({**self.q,'period':'WEEK'});bar=w['bars'][-1]
        self.assertFalse(bar['complete']);self.assertEqual(bar['constituent_count'],3);self.assertEqual(bar['volume'],sum(x['volume'] for x in bar['members']));self.assertIsNone(bar['amount'])
        month=self.engine.read({**self.q,'period':'MONTH'});self.assertFalse(month['bars'][-1]['complete']);self.assertTrue(all(r['date']<='2026-09-23' for r in month['bars'][-1]['members']))
    def test_week_holiday_end_and_progress(self):
        a=self.engine.read({**self.q,'end_date':'2026-09-24'});v=a['volume_context'];self.assertTrue(v['complete']);self.assertEqual(v['comparison_basis'],'FULL_PERIOD')
        b=self.engine.read(self.q)['volume_context'];self.assertEqual(b['target_trading_days'],3);self.assertTrue(all(s['trading_days']==3 for s in b['samples']))
    def test_day_target_excluded_and_month_progress(self):
        v=self.engine.read({**self.q,'volume_period':'DAY'})['volume_context'];self.assertEqual(v['actual_samples'],20);self.assertLess(v['sample_end'],v['target_end']);self.assertAlmostEqual(v['ratio'],v['target_volume']/v['historical_average'])
        m=self.engine.read({**self.q,'volume_period':'MONTH'})['volume_context'];self.assertTrue(all(s['trading_days']==m['target_trading_days'] for s in m['samples']));self.assertLess(m['actual_samples'],20)
    def test_gaps_and_zero_not_filled(self):
        self.adapter.rows=[r for r in rows() if r['day']!='2026-09-22']
        # Keep the benchmark intact to distinguish absent stock records from market closure.
        original=self.adapter.fetch
        self.adapter.fetch=lambda s,c:copy.deepcopy(rows()[-c:]) if s=='sh000001' else original(s,c)
        value=self.engine.read(self.q);self.assertIn('2026-09-22',value['quality']['gaps_or_suspensions']);self.assertIsNone(value['volume_context']['ratio'])
        zero=copy.deepcopy(rows());zero[-2]['volume']='0';raw,_=normalize(zero,'2026-09-23',self.now,'X');g=aggregate(raw,'DAY','2026-09-23',[r['date'] for r in raw],TradingCalendar().is_open);self.assertFalse(g[-1]['valid_volume'])
    def test_singleflight_and_independent_cache(self):
        with ThreadPoolExecutor(6) as pool:values=list(pool.map(lambda _:self.engine.read(self.q),range(6)))
        self.assertEqual(self.adapter.calls,2);self.assertEqual(len({v['fingerprint'] for v in values}),1)
        before=self.adapter.calls;self.engine.read({**self.q,'period':'WEEK','limit':31});self.assertEqual(self.adapter.calls,before)
    def test_contract_and_future_dates_rejected(self):
        for patch in ({'period':'5MIN'},{'adjustment':'QFQ'},{'end_date':'2027-01-01'},{'symbol':'../../data'}):
            with self.assertRaises(HistoryError):self.engine.read({**self.q,**patch})
        import jsonschema
        schema=json.loads((Path(__file__).resolve().parents[1]/'contracts/history/bars.schema.json').read_text(encoding='utf-8'))
        jsonschema.validate(self.engine.read(self.q),schema)
    def test_cleanup_external_evidence_failure_resumes(self):
        from unittest.mock import patch
        with self.store.db() as db:db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',('HIST-expiry','expiry-job','2026-09-24','2026-09-24','FAILED','{}','{}',None,None))
        with patch('engines.live.provider_request_repository.expire_inputs',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):self.store.expire('2026-09-28')
        with patch('engines.live.provider_request_repository.expire_inputs') as cleanup:
            self.store.expire('2026-09-28');self.assertEqual(cleanup.call_args.args[1],['HIST-expiry'])
        with self.store.db() as db:self.assertIsNone(db.execute("SELECT value FROM maintenance WHERE key='pending_expiry'").fetchone())
    def test_historical_job_isolated_immutable_and_idempotent(self):
        provider=Provider();service=HistoricalAnalysis(self.engine,self.store,provider,lambda:{},'TEST')
        try:
            payload={**self.q,'request_id':'test-history-001'};job=service.submit(payload)
            for _ in range(100):
                job=self.store.job(job['id'])
                if job['status'] not in ('QUEUED','RUNNING'):break
                time.sleep(.02)
            self.assertEqual(job['status'],'SUCCEEDED',job['error']);self.assertEqual(service.submit(payload)['id'],job['id']);self.assertEqual(len(provider.inputs),1)
            f=provider.inputs[0];self.assertIsNone(f['portfolio_context']);self.assertNotIn('previous_advisory',f);self.assertNotIn('events',f)
            for forbidden in ('account','notification','runtime','success_observer'):self.assertFalse(hasattr(service,forbidden))
            future=copy.deepcopy(f);future['bars'][-1]['date']='2026-09-24'
            with self.assertRaises(HistoryError):evidence(future,PROMPT,SCHEMA)
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store.db() as db:db.execute("UPDATE jobs SET opinion='{}' WHERE id=?",(job['id'],))
            with self.store.db() as db:db.execute("INSERT INTO preferences VALUES('bj920161','{}')")
            self.store.expire('2026-09-28');self.assertEqual(self.store.job(job['id'])['status'],'EXPIRED')
            with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM preferences').fetchone()[0],1)
        finally:service.close()
    def test_read_only_cutoff_invalid_day_does_not_call_provider(self):
        p=Provider();s=HistoricalAnalysis(self.engine,self.store,p,lambda:{},'TEST')
        try:
            job=s.submit({**self.q,'end_date':'2026-09-20','request_id':'holiday-001'})
            for _ in range(100):
                job=self.store.job(job['id'])
                if job['status']=='FAILED':break
                time.sleep(.01)
            self.assertEqual(job['status'],'FAILED');self.assertFalse(p.inputs)
        finally:s.close()
    def test_acquisition_day_cleanup_not_historical_target_day(self):
        self.engine.read({**self.q,'end_date':'2025-03-03'})
        self.assertEqual(self.store.expire('2026-09-24')['daily_cache_rows'],0)
        self.assertEqual(self.store.expire('2026-09-28')['daily_cache_rows'],2)
    def test_new_business_code_is_portable(self):
        root=Path(__file__).resolve().parents[1]
        for directory in ('engines/history','contracts/history'):
            for p in (root/directory).glob('*.py'):
                body=p.read_text(encoding='utf-8');self.assertNotIn('D:\\',body);self.assertNotIn('127.0.0.1',body);self.assertNotIn('powershell',body.lower())
    def test_http_attempt_allowance_includes_internal_retries(self):
        import httpx,sqlite3
        from adapters.ai.request_guard import RequestGuard,RequestGuardError
        budget=self.root/'attempts.db';guard=RequestGuard({'target_input_tokens':32000,'token_count_method':'TEST_ESTIMATE','input_builder_version':'history-test'},budget_path=budget)
        for i in range(3):guard.before(httpx.Request('POST','https://api.deepseek.com/responses',json={'input':json.dumps({'round':i}),'max_output_tokens':100}))
        with self.assertRaises(RequestGuardError):guard.before(httpx.Request('POST','https://api.deepseek.com/responses',json={'input':'{}'}))
        from contextlib import closing
        with closing(sqlite3.connect(budget)) as db:self.assertEqual(db.execute('select count(*) from attempts').fetchone()[0],3)
    def test_expiry_keeps_active_tasks_and_recovery_never_retries(self):
        with self.store.db() as db:db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',('HIST-active','active-job','2026-09-24','2026-09-24','RUNNING','{}','{}',None,None))
        self.store.expire('2026-09-28');self.assertEqual(self.store.job('HIST-active')['status'],'RUNNING')
        restarted=HistoryStore(self.root);self.assertEqual(restarted.job('HIST-active')['status'],'INTERRUPTED')
        restarted.expire('2026-09-28');self.assertEqual(restarted.job('HIST-active')['status'],'EXPIRED')
    def test_history_fetch_does_not_hold_live_api_or_source_lock(self):
        from tests.agent_auto_fixture import AgentAutoFixture
        from app.shell.server import make_server
        from threading import Event,Thread
        from urllib.request import urlopen
        from urllib.parse import urlencode
        f=AgentAutoFixture(self.root/'app');router=next(r for r in f.app.routers if type(r).__name__=='HistoryRouter')
        entered=Event();release=Event();original=self.adapter.fetch
        def slow(symbol,count):entered.set();release.wait(3);return original(symbol,count)
        self.adapter.fetch=slow;router.bars=self.engine
        server=make_server(f.app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start();pool=ThreadPoolExecutor(1)
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            future=pool.submit(lambda:json.load(urlopen(base+'/api/history/bars?'+urlencode(self.q))))
            self.assertTrue(entered.wait(2));start=time.monotonic()
            self.assertEqual(urlopen(base+'/live').status,200);self.assertEqual(urlopen(base+'/healthz').status,200)
            self.assertLess(time.monotonic()-start,.5);release.set();self.assertTrue(future.result(timeout=5)['bars'])
        finally:
            release.set();pool.shutdown();server.shutdown();server.server_close();thread.join();router.close();f.close()

if __name__=='__main__':unittest.main()
