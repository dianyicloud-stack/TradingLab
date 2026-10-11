"""Owner retention under trading clocks; no production or real Provider access."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from tempfile import TemporaryDirectory
from copy import deepcopy
from unittest.mock import patch,Mock
from contextlib import closing
import unittest,json,sqlite3,uuid
from tests.support.native import NativeFixture
from tests.test_market_agent import frame,LocalPort
from tests.account_fixture import quote
from engines.live.retention import LiveRetention
from engines.live.market_agent.service import AgentService
from engines.live.market_agent.retention import AgentRetention
from engines.account.rules import TradingCalendar
from contracts.maintenance import RetentionBoundary,SNAPSHOT_OPTIONS
from shared.storage.maintenance import snapshot,sha,checked
from app.system.maintenance import MaintenanceService
from app.system.artifact_retention import ArtifactRetention
from shared.config import ScopedStore

ROOT=Path(__file__).resolve().parents[1]

class LiveLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT/'tests',prefix='lifecycle-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.f=NativeFixture(self.root);self.addCleanup(self.f.close)
        self.a=self.f.advisory;self.owner=LiveRetention(self.a);self.a.market_is_open=lambda _:True
        self.f.append();self.a.ingest();self.first=self.a.analyze('bj920161');self.sid=self.first['tracking_session_id']
        self.boundary=RetentionBoundary('2026-09-10',run_id='retain-2026-09-10')
    def clean(self,b=None):
        for _ in range(30):
            r=self.owner.step(b or self.boundary,2)
            if r['status']=='DONE':return
        self.fail('maintenance did not converge')
    def test_daily_detail_expires_identity_and_success_watermark_survive(self):
        before=self.a.runtime.cursor(self.sid);self.clean()
        self.assertIsNone(self.a.opinions.by_id(self.first['advisory_id']));self.assertEqual(before,self.a.runtime.cursor(self.sid))
        self.assertTrue(self.a.runtime.expired(self.sid));self.assertEqual(self.a.runtime.ingested_facts(self.sid,'OBSERVATION'),[])
        self.a.ingest();self.assertEqual(self.a.runtime.ingested_facts(self.sid,'OBSERVATION'),[])
        calls=len(self.f.provider.calls)
        with self.assertRaisesRegex(Exception,'清理'):self.a.analyze('bj920161')
        self.assertEqual(len(self.f.provider.calls),calls)
    def test_manual_reference_and_today_opinion_remain(self):
        self.clean(RetentionBoundary('2026-09-10',(self.first['advisory_id'],)))
        self.assertEqual(self.a.opinions.by_id(self.first['advisory_id']),self.first)
        self.assertIsNotNone(self.a.opinions.input(self.first['input_id']))
    def test_current_day_never_deleted(self):
        self.clean(RetentionBoundary('2026-09-09'));self.assertEqual(self.a.opinions.count(),1)
    def test_running_or_queued_task_defers(self):
        with self.a.runtime.connect() as db:db.execute("UPDATE live_analysis_requests SET status='RUNNING'")
        self.assertEqual(self.owner.step(self.boundary)['status'],'DEFERRED');self.assertEqual(self.a.opinions.count(),1)
    def test_expiry_during_input_build_cannot_enqueue_or_charge(self):
        self.f.append();freeze=self.a.freeze;calls=len(self.f.provider.calls)
        def racing(*args):
            result=freeze(*args);self.clean();return result
        with patch.object(self.a,'freeze',side_effect=racing):
            with self.assertRaisesRegex(Exception,'提交给AI'):self.a.analyze('bj920161')
        self.assertEqual(len(self.f.provider.calls),calls);self.assertFalse(self.owner.busy())
    def test_interruption_between_owner_deletions_reconciles(self):
        with patch('engines.live.provider_request_repository.expire_inputs',side_effect=RuntimeError('test interrupted')):
            with self.assertRaises(RuntimeError):self.owner.step(self.boundary)
        self.clean();self.assertEqual(self.owner.step(self.boundary)['status'],'DONE')
        with self.a.opinions.connect(True) as db:self.assertEqual(db.execute('select count(*) from retention_tombstones').fetchone()[0],1)
    def test_read_expired_history_is_explicit(self):
        self.clean();router=next(r for r in self.f.app.routers if type(r).__name__=='LiveRouter');router.read_model=Mock()
        status,data,_=router.route('GET','/api/live/bj920161/advisory/history',{'tracking_session_id':self.sid})
        self.assertEqual(status,200);self.assertEqual(data['availability'],'RETENTION_EXPIRED')
    def test_imported_session_without_ingestion_uses_explicit_opinion_marker(self):
        with self.a.runtime.connect() as db:db.execute('DELETE FROM live_ingestion WHERE session_id=?',(self.sid,))
        before=self.a.runtime.cursor(self.sid);self.assertFalse(self.a.history_expired(self.sid));self.clean()
        self.assertFalse(self.a.runtime.expired(self.sid));self.assertTrue(self.a.history_expired(self.sid));self.assertFalse(self.a.history_expired('unknown'))
        router=next(r for r in self.f.app.routers if type(r).__name__=='LiveRouter');router.read_model=Mock()
        for kind in ('history','timeline'):
            status,data,_=router.route('GET','/api/live/bj920161/advisory/'+kind,{'tracking_session_id':self.sid})
            self.assertEqual(status,200);self.assertEqual(data['availability'],'RETENTION_EXPIRED')
        self.assertEqual(before,self.a.runtime.cursor(self.sid))
    def test_history_page_is_bounded_and_stable_under_new_opinions(self):
        for _ in range(14):self.f.append();self.a.analyze('bj920161')
        p=self.a.opinions.history_page('bj920161',self.sid,10);self.assertEqual(len(p['opinions']),10)
        self.f.append();new=self.a.analyze('bj920161')
        p2=self.a.opinions.history_page('bj920161',self.sid,10,p['next_before'],p['anchor'])
        ids=[x['advisory_id'] for x in p['opinions']+p2['opinions']]
        self.assertEqual(len(ids),15);self.assertEqual(len(set(ids)),15);self.assertNotIn(new['advisory_id'],ids)
    def test_snapshot_restores_all_owner_rows_and_hashes(self):
        saved=self.owner.snapshot(self.boundary.run_id);self.clean()
        path=self.a.opinions.store.path('maintenance-backups/'+self.boundary.run_id+'/advisory.db')
        self.assertEqual(sha(path),saved['opinions']['files']['advisory.db']['sha256'])
        with closing(sqlite3.connect(path)) as db:self.assertEqual(db.execute('select count(*) from advisory_opinions').fetchone()[0],1)
    def test_account_fees_t1_projection_and_rebuild_unchanged(self):
        f=self.f;p=f.p;account=f.create();aid=account['account_id'];now=f.now.isoformat()
        intent={'symbol':'bj920161','portfolio_action':'OPEN','target_weight':.15,'source':'LIVE_AI_CONFIRMED','advisory_id':self.first['advisory_id'],'source_ref':self.first['advisory_id'],'advisory_session_date':self.first['session_date']}
        result=p.engine.submit(aid,intent,quote(time=now),now);self.assertGreater(result['executed_qty'],0)
        self.assertGreater(result['fees']['total'],0)
        f.now+=timedelta(days=1);f.append(price=11)
        # Explicit clock advance through normal owner engine.
        day2=f.now.isoformat();before=p.engine.state(aid,day2);ledger=p.engine.ledger(aid);rebuilt=p.engine._rebuild(ledger)
        self.assertEqual(p.engine.state(aid,now)['positions']['bj920161']['available_qty'],0)
        self.assertEqual(before['positions']['bj920161']['available_qty'],result['executed_qty'])
        refs=p.retention_evidence(preserve=True);self.assertIn(self.first['advisory_id'],refs)
        self.clean(RetentionBoundary('2026-09-10',tuple(refs)))
        self.assertEqual(ledger,p.engine.ledger(aid));self.assertEqual(rebuilt,p.engine._rebuild(p.engine.ledger(aid)));self.assertEqual(before,p.engine.state(aid,day2))
        sell=p.engine.submit(aid,{'symbol':'bj920161','portfolio_action':'EXIT','source':'LIVE_MANUAL'},quote(price=11,time=day2),day2)
        self.assertGreater(sell['executed_qty'],0);self.assertGreater(p.engine.state(aid,day2)['realized_pnl'],0)
        with p.engine.repository.transaction(aid) as db:self.assertEqual(db.execute('select count(*) from retained_advisory_evidence').fetchone()[0],1)

class AgentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT/'tests',prefix='lifecycle-agent-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=datetime.fromisoformat('2026-09-14T09:35:40+08:00');self.cal=TradingCalendar()
        self.s=AgentService(self.root,clock=lambda:self.now,calendar=self.cal.is_open);self.addCleanup(lambda:self.s.close())
        self.s.command({'schema_version':'1.0','source':'TEST','action':'ADD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':0})
    def sample(self):
        self.s.command({'schema_version':'1.0','source':'TEST','action':'BOARD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':self.s.repo.command_version()})
        value=frame(self.now);value['dataset']['volumeHistoryBars']=[{'date':(self.now.date()-timedelta(days=i)).isoformat(),'time':'09:35:00','volume':1000+i,'close':10} for i in range(1,31)]
        self.s.cycle({'bj920161':value});self.assertEqual(self.s.errors,[])
        return value
    def clean(self,interrupt=False):
        owner=AgentRetention(self.s);p=owner.plan();self.assertFalse(p['blocked'],p)
        command={'schema_version':'1.0','source':'TEST','keep_day':p['keep_day'],'run_id':'retain-'+p['keep_day'],'confirmation':'OWNER_RETENTION_V1'}
        self.s.command({**command,'action':'RETENTION_BACKUP'})
        for _ in range(100):
            result=self.s.command({**command,'action':'RETENTION_APPLY'})
            if interrupt or result['status']=='DONE':return result
        self.fail('did not converge')
    def test_five_trading_days_bounded_detail_and_no_reingestion(self):
        counts=[];sizes=[]
        for n in range(5):
            self.now=datetime.fromisoformat(f'2026-09-{14+n}T09:35:40+08:00');self.sample();self.clean()
            facts=self.s.repo.facts();counts.append(len(facts));sizes.append(self.s.repo.path.stat().st_size)
            self.assertTrue(all(f['payload'].get('session_date',self.now.date().isoformat())>=self.now.date().isoformat() for f in facts))
            self.assertEqual(len(self.s.query()['sessions']),1)
            count=len(facts);self.clean();self.assertEqual(len(self.s.repo.facts()),count)
        self.assertLess(max(counts)-min(counts),6)
        self.assertLessEqual(len(list((self.root/'maintenance-backups').glob('*/manifest.json'))),2)
    def test_weekend_holiday_and_failed_new_day(self):
        self.sample();self.now=datetime.fromisoformat('2026-09-15T09:35:40+08:00')
        self.assertTrue(AgentRetention(self.s).plan()['blocked'])
        self.now=datetime.fromisoformat('2026-09-19T09:35:40+08:00');self.assertTrue(AgentRetention(self.s).plan()['blocked'],'Monday proof cannot cover missing intervening trading days')
        self.now=datetime.fromisoformat('2026-09-24T09:35:40+08:00');self.sample()
        self.now=datetime.fromisoformat('2026-09-25T09:35:40+08:00');self.assertFalse(AgentRetention(self.s).plan()['blocked'])
    def test_lookback_exact_before_after_cleanup_and_restart(self):
        self.sample();self.now+=timedelta(days=1);self.sample()
        value=self.s.worker.call({'op':'maintenance_baselines','day':self.now.date().isoformat()});bars=value['samples']['bj920161']
        args=[bars,self.now.date().isoformat(),'09:30','09:35',2500,20]
        before=self.s.worker.call({'op':'parity','method':'samePeriodVolumeStats','args':args,'now':self.now.isoformat()});self.assertGreater(before['sample'],0)
        self.clean();after=self.s.worker.call({'op':'parity','method':'samePeriodVolumeStats','args':args,'now':self.now.isoformat()});self.assertEqual(before,after)
        with self.s.repo.connect() as db:saved=json.loads(db.execute('select payload from retention_readiness').fetchone()[0])
        self.assertEqual(bars,saved['samples']['bj920161']);self.s.close();self.s=AgentService(self.root,clock=lambda:self.now,calendar=self.cal.is_open)
        self.assertEqual(before,self.s.worker.call({'op':'parity','method':'samePeriodVolumeStats','args':[saved['samples']['bj920161'],*args[1:]],'now':self.now.isoformat()}))
    def test_missing_lookback_fails_closed(self):
        self.s.cycle({'bj920161':frame(self.now)});self.assertTrue(AgentRetention(self.s).plan()['blocked'])
    def test_crash_restart_and_deleted_stock_not_resurrected(self):
        self.sample();old=self.s.repo.facts();self.now+=timedelta(days=1);self.sample();self.clean(interrupt=True)
        self.s.close();self.s=AgentService(self.root,clock=lambda:self.now,calendar=self.cal.is_open);self.clean()
        state=self.s.repo.checkpoint()[1];count=len(self.s.repo.facts());self.s.repo.commit(state,[(f['kind'],f['identity'],f['payload']) for f in old]);self.assertEqual(len(self.s.repo.facts()),count)

class StorageSafetyTests(unittest.TestCase):
    def test_managed_artifacts_cap_and_manual_unknown_protection(self):
        with TemporaryDirectory(dir=ROOT/'tests') as tmp:
            root=Path(tmp);owner=ArtifactRetention(root)
            (root/'manual.txt').write_text('manually saved')
            for i in range(5):
                (root/f'{i}.txt').write_text('test output')
                owner.register(str(i),'TEST_ARTIFACT',[f'{i}.txt'],finished_at=f'2026-09-0{i+1}T00:00:00+00:00',pinned=i==0)
            (root/'1.txt').write_text('user edited after test')
            self.assertEqual(owner.preview()['records'],2)
            result=owner.step();self.assertEqual(result['files_deleted'],1)
            self.assertTrue((root/'manual.txt').exists());self.assertTrue((root/'0.txt').exists());self.assertTrue((root/'1.txt').exists())
            self.assertTrue((root/'3.txt').exists());self.assertTrue((root/'4.txt').exists())
    def test_unknown_path_refused(self):
        with self.assertRaises(ValueError):checked(ROOT/'tests',ROOT/'data')
    def test_only_snapshot_is_never_removed(self):
        with TemporaryDirectory(dir=ROOT/'tests') as tmp:
            root=Path(tmp);dbpath=root/'test.db'
            with closing(sqlite3.connect(dbpath)) as db:db.execute('create table x(a)');db.commit()
            for day in range(1,6):snapshot(root,{'test.db':dbpath},f'run-{day}',**SNAPSHOT_OPTIONS)
            self.assertEqual(len(list((root/'maintenance-backups').glob('*/manifest.json'))),2)
            self.assertTrue((root/'maintenance-backups/run-5/test.db').exists())
            self.assertTrue((root/'maintenance-backups/run-1/test.db').exists(),'first verified recovery snapshot stays protected')
    def test_partial_backup_counts_toward_quota(self):
        with TemporaryDirectory(dir=ROOT/'tests') as tmp:
            root=Path(tmp);dbpath=root/'test.db'
            with closing(sqlite3.connect(dbpath)) as db:db.execute('create table x(a)');db.commit()
            partial=root/'maintenance-backups/interrupted';partial.mkdir(parents=True);(partial/'test.db').write_bytes(b'x'*20000)
            with self.assertRaisesRegex(ValueError,'BACKUP_SPACE_REQUIRED'):
                snapshot(root,{'test.db':dbpath},'next',cap=24000,max_count=2,valid_days=14)

class MaintenanceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT/'tests',prefix='maintenance-contract-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.f=NativeFixture(self.root);self.addCleanup(self.f.close);self.a=self.f.advisory;self.a.market_is_open=lambda _:True
        self.f.append();self.a.ingest();self.opinion=self.a.analyze('bj920161')
        self.agent=Mock();self.agent.query.return_value={'capabilities':['DAILY_RETENTION_V1','RETENTION_VALIDATION_V2'],'source':'TEST'}
        self.agent.command.side_effect=lambda p:{'owner':'MARKET_AGENT','keep_day':'2026-09-10','blocked':False,'records':0,'estimated_logical_bytes':0,'protected_sessions':[]} if p['action']=='RETENTION_PREVIEW' else {'status':'DONE'}
        self.service=MaintenanceService(ScopedStore(self.root/'system',boundary=self.root),self.a,self.agent,self.f.p,lambda:[],TradingCalendar())
    def test_default_disabled_and_get_has_no_owner_reads(self):
        from app.system.maintenance import MaintenanceRouter
        r=MaintenanceRouter(self.service);r.route('GET','/api/system/maintenance');self.agent.query.assert_not_called()
        self.assertEqual(self.service.request('apply')['status'],'POLICY_DISABLED')
        self.service.run_once(apply=True);self.assertIsNotNone(self.a.opinions.by_id(self.opinion['advisory_id']))
    def test_contract_order_snapshots_before_delete_and_idempotence(self):
        self.service.request('enable',{'confirmation':'ENABLE_LATEST_READY_DAY_RETENTION'})
        first=self.service.run_once(True);self.assertEqual(first['status'],'DONE',first)
        actions=[c.args[0]['action'] for c in self.agent.command.call_args_list];self.assertLess(actions.index('RETENTION_BACKUP'),actions.index('RETENTION_APPLY'))
        self.assertIsNone(self.a.opinions.by_id(self.opinion['advisory_id']))
        self.agent.command.reset_mock();again=self.service.run_once(True)
        self.assertEqual(again['last_result']['run_id'],'retain-2026-09-10');self.assertNotIn('RETENTION_APPLY',[c.args[0]['action'] for c in self.agent.command.call_args_list])
    def test_local_backup_switch_persists_without_skipping_account_protection(self):
        self.service.configure_local_snapshots(False)
        self.service.request('enable',{'confirmation':'ENABLE_LATEST_READY_DAY_RETENTION'})
        with patch.object(self.service.live,'snapshot',side_effect=AssertionError('no local snapshot')),patch.object(self.service.live,'snapshot_requirements',side_effect=AssertionError('no local snapshot preflight')),patch.object(self.f.p,'retention_evidence',wraps=self.f.p.retention_evidence) as evidence:
            result=self.service.run_once(True)
        self.assertEqual(result['status'],'DONE');self.assertEqual(result['checks']['snapshots'],'LOCAL_DISABLED')
        self.assertTrue(any(c.kwargs.get('preserve') for c in evidence.call_args_list));self.assertFalse(self.service.policy['local_snapshots_enabled'])
        self.assertFalse(json.loads(self.service.policy_path.read_text())['local_snapshots_enabled'])
        self.assertFalse(list(self.root.rglob('maintenance-backups')))

    def test_agent_failure_after_live_commit_recovers_after_restart(self):
        self.service.policy['enabled']=True;original=self.agent.command.side_effect
        def interrupted(p):
            if p['action']=='RETENTION_APPLY':raise OSError('interrupted TEST IPC')
            return original(p)
        self.agent.command.side_effect=interrupted;first=self.service.run_once(True);self.assertEqual(first['status'],'DEFERRED');self.assertEqual(first['journal']['phase'],'AGENT')
        self.agent.command.side_effect=original;second=self.service.run_once(True);self.assertEqual(second['status'],'DONE')
    def test_manual_case_contract_uses_source_advisory_id(self):
        self.service.manual_refs=lambda:[{'source_advisory_id':self.opinion['advisory_id']}]
        self.service.policy['enabled']=True;result=self.service.run_once(True);self.assertEqual(result['status'],'DONE')
        self.assertIsNotNone(self.a.opinions.by_id(self.opinion['advisory_id']))

if __name__=='__main__':unittest.main()
