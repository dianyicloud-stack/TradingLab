"""History reading, billing reuse and local-day TTL; no real Provider or Telegram."""
import json,time,unittest
from datetime import timedelta
from unittest.mock import patch
from tests import test_history as fixture
from tests.test_history import Provider
from engines.history.service import HistoricalAnalysis,evidence,PROMPT,SCHEMA
from engines.history.store import HistoryStore
from contracts.live.presentation import volume,chinese_prose

class ResultsTests(unittest.TestCase):
    setUp=fixture.HistoryTests.setUp
    def tearDown(self):self.doCleanups();fixture.HistoryTests.tearDown(self)
    def service(self,provider=None):
        p=provider or Provider();s=HistoricalAnalysis(self.engine,self.store,p,lambda:{},'TEST',lambda symbol:'测试股票'+symbol[-2:])
        self.addCleanup(s.close);return s,p
    def finish(self,s,key,**patches):
        j=s.submit({**self.q,'request_id':key,**patches})
        for _ in range(100):
            j={**j,**self.store.job(j['id'])}
            if j['status'] not in ('QUEUED','RUNNING'):break
            time.sleep(.01)
        self.assertEqual(j['status'],'SUCCEEDED',j.get('error'));return j
    def test_volume_boundaries(self):
        examples=[(9999,'9999'),(9999.99,'9999.99'),(10000,'1W'),(10500,'1.05W'),(100000,'10W'),(105000,'10.5W'),(1000000,'100W'),(2354661,'235.47W'),(32713743,'3271.37W'),(100000000,'10000W'),(-10500,'-1.05W'),(0,'0'),(None,'数据未提供')]
        for n,text in examples:self.assertEqual(volume(n),text)
    def test_safe_chinese_projection_and_original_immutable(self):
        p=Provider();p.analyze_history=lambda *a:{'analysis':{'conclusion':'volume_context：ratio=0.72；amount=null','basis':'成交量2354661股，不超过327.14万股，价格20.44元。','next_observation':'未确认，不应买入。','limitations':'custom_variable={1} https://example.com/amount'}}
        s,_=self.service(p);job=self.finish(s,'chinese-001');raw=job['opinion'];shown=s.detail(job['id'])['display']['analysis']
        self.assertEqual(shown['conclusion'],'量能对比：量比0.72倍；成交额数据未提供');self.assertIn('235.47W股',shown['basis']);self.assertIn('不超过327.14W股，价格20.44元',shown['basis']);self.assertEqual(shown['next_observation'],'未确认，不应买入。');self.assertIn('诊断原文',shown['limitations']);self.assertEqual(self.store.job(job['id'])['opinion'],raw)
        self.assertEqual(chinese_prose('amounted ratio_extra'),'本段含未识别的技术表达，请展开诊断原文核对。')
        self.assertEqual(chinese_prose('成交量2354661；样本均值3271374.3；成交量恢复至约3271374，价格20.44元。',(2354661,3271374.3)),
            '成交量235.47W；样本均值327.14W；成交量恢复至约327.14W，价格20.44元。')
        self.assertEqual(chinese_prose('历史平均123456元',(123456,)), '历史平均123456元')
        self.assertEqual(chinese_prose('成交量100000手'), '成交量100000手')
    def test_provider_readable_evidence_keeps_raw_numbers_and_cutoff(self):
        s,p=self.service();self.finish(s,'evidence-001');f=p.inputs[0];prepared,meta=evidence(f,PROMPT,SCHEMA)
        self.assertEqual(prepared['volume_context'],f['volume_context']);self.assertEqual(prepared['bars'],f['bars'])
        self.assertIn('量能对比',prepared['readable_evidence']);self.assertIn('目标成交量',prepared['readable_evidence']);self.assertNotIn('volume_context',prepared['readable_evidence']);self.assertIn('不输出内部变量名',PROMPT);self.assertEqual(meta['target_input_tokens'],32000)
    def test_same_context_reuse_force_and_model_version_change(self):
        s,p=self.service();a=self.finish(s,'reuse-first');b=self.finish(s,'reuse-second');self.assertEqual(a['id'],b['id']);self.assertTrue(b['reused']);self.assertEqual(len(p.inputs),1)
        c=self.finish(s,'reuse-force',force_reanalysis=True);self.assertNotEqual(a['id'],c['id']);self.assertEqual(len(p.inputs),2)
        s.settings=lambda:{'model':'another-test-model'};self.finish(s,'reuse-model');self.assertEqual(len(p.inputs),3)
        with self.store.db() as db:db.execute('DELETE FROM daily')
        next(r for r in self.adapter.rows if r['day']==self.q['end_date'])['volume']='98765'
        self.finish(s,'reuse-version');self.assertEqual(len(p.inputs),4)
    def test_two_stocks_pagination_restart_and_backfill(self):
        s,p=self.service()
        for i in range(22):self.finish(s,'pages-'+str(i).zfill(4),symbol='sh688601' if i%2 else 'bj920161',force_reanalysis=True)
        day=self.now.date().isoformat();a=self.store.today(day);b=self.store.today(day,a['next_cursor'])
        self.assertEqual(a['total'],22);self.assertEqual(len(a['items']),20);self.assertEqual(len(b['items']),2);self.assertFalse(set(x['id'] for x in a['items'])&set(x['id'] for x in b['items']))
        self.assertEqual({x['symbol'] for x in a['items']},{'bj920161','sh688601'})
        self.assertNotIn('input',a['items'][0]);self.assertNotIn('opinion',a['items'][0])
        s.close()
        with self.store.db() as db:db.execute('DELETE FROM result_index')
        restored=HistoryStore(self.root);self.assertEqual(restored.today(day)['total'],22)
        again=HistoricalAnalysis(self.engine,restored,p,lambda:{},'TEST');self.addCleanup(again.close)
        result=again.submit({**self.q,'request_id':'restarted-reuse'});self.assertTrue(result['reused']);self.assertEqual(len(p.inputs),22)
    def test_next_calendar_day_ttl_weekend_and_preserves_preferences(self):
        s,p=self.service();a=self.finish(s,'expire-today')
        with self.store.db() as db:db.execute("INSERT INTO preferences VALUES('bj920161','{}')")
        self.assertEqual(self.store.today('2026-09-25')['total'],1)
        self.now+=timedelta(days=1) # Saturday: no trading-calendar gate.
        self.assertEqual(s.detail(a['id'])['status'],'EXPIRED') # GET does not mutate storage.
        self.assertEqual(self.store.job(a['id'])['status'],'SUCCEEDED')
        s.maintenance_once();self.assertEqual(self.store.job(a['id'])['status'],'EXPIRED');self.assertEqual(self.store.today('2026-09-26')['total'],0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM result_index').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM daily').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM preferences').fetchone()[0],1)
        self.assertEqual(len(p.inputs),1)
    def test_background_startup_cleanup_without_browser(self):
        s,p=self.service();a=self.finish(s,'restart-expire');s.close();self.now+=timedelta(days=2)
        restored=HistoryStore(self.root);other=HistoricalAnalysis(self.engine,restored,p,lambda:{},'TEST');self.addCleanup(other.close);other.start_maintenance()
        for _ in range(100):
            if restored.job(a['id'])['status']=='EXPIRED':break
            time.sleep(.01)
        self.assertEqual(restored.job(a['id'])['status'],'EXPIRED');self.assertEqual(len(p.inputs),1)
    def test_task_finishing_after_midnight_belongs_to_finish_day(self):
        p=Provider();original=p.analyze_history
        def across_midnight(*args):
            self.now=self.now.replace(hour=0,minute=1)+timedelta(days=1)
            return original(*args)
        p.analyze_history=across_midnight;s,p=self.service(p);j=self.finish(s,'midnight-finish')
        s.maintenance_once()
        self.assertEqual(self.store.job(j['id'])['status'],'SUCCEEDED')
        self.assertEqual(self.store.today('2026-09-26')['total'],1)
    def test_pending_duplicate_one_provider_call(self):
        from threading import Event
        p=Provider();entered=Event();release=Event();original=p.analyze_history
        def delayed(*args):entered.set();release.wait(3);return original(*args)
        p.analyze_history=delayed;s,p=self.service(p)
        try:
            a=s.submit({**self.q,'request_id':'inflight-first'});self.assertTrue(entered.wait(1))
            b=s.submit({**self.q,'request_id':'inflight-second'});self.assertEqual(a['id'],b['id']);self.assertTrue(b['reused'])
        finally:release.set()

if __name__=='__main__':unittest.main()
