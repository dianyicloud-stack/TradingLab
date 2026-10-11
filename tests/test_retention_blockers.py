"""Production-shaped cold upgrade, scope-aware errors, and real owner completion."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timedelta
from contextlib import closing
from unittest.mock import patch
import unittest,os,json,sqlite3,subprocess,uuid
from app.system.artifact_retention import scan_capacity,scan_safety
from app.system.maintenance import MaintenanceService
from engines.live.market_agent.service import AgentService
from engines.live.market_agent.retention import AgentRetention
from engines.account.rules import TradingCalendar
from shared.config import ScopedStore
from tests.test_market_agent import frame,LocalPort
from tests.support.native import NativeFixture
from tests.account_fixture import quote
ROOT=Path(__file__).resolve().parents[1]

class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT/'tests');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bad=self.root/'tests/opaque';self.bad.mkdir(parents=True);(self.root/'visible').write_bytes(b'known')
    def scan(self,path=None):
        original=os.scandir;bad=path or self.bad
        def deny(p):
            if Path(p)==bad:raise PermissionError('TEST DENIAL')
            return original(p)
        with patch('os.scandir',side_effect=deny):return scan_capacity(self.root)
    def test_proven_excluded_not_candidate_partial_is_lower_bound_and_retry(self):
        s=self.scan();self.assertEqual(s['status'],'PARTIAL');self.assertTrue(s['total_is_lower_bound']);self.assertEqual(s['known_bytes'],5)
        e=scan_safety(s,self.root,[self.root/'data',self.root/'artifacts']);self.assertFalse(e[0]['blocks_cleanup']);self.assertTrue(self.bad.exists())
        self.assertEqual(scan_capacity(self.root)['status'],'COMPLETE')
    def test_candidate_and_evidence_overlap_refuse(self):
        for owner in (self.bad,self.bad/'account.db',self.root/'tests'):
            self.assertTrue(scan_safety(self.scan(),self.root,[owner])[0]['blocks_cleanup'])
    def test_overflow_checks_every_path_without_unbounded_log(self):
        bad={self.bad}
        for i in range(45):
            p=self.root/'tests'/str(i);p.mkdir();bad.add(p)
        original=os.scandir;owners=[self.root/'data',self.root/'artifacts']
        def deny(p):
            if Path(p) in bad:raise PermissionError('TEST')
            return original(p)
        with patch('os.scandir',side_effect=deny):s=scan_capacity(self.root,safety_project=self.root,owner_roots=owners)
        self.assertEqual(s['error_count'],46);self.assertEqual(len(s['errors']),32)
        self.assertEqual(s['status'],'PARTIAL');self.assertTrue(s['total_is_lower_bound'])
        self.assertFalse(any(x['blocks_cleanup'] for x in scan_safety(s,self.root,owners)))
        self.assertTrue(scan_safety(s,self.root,[*owners,self.root/'tests'])[-1]['blocks_cleanup'])
        # An overlapping owner hidden beyond the display limit must still block.
        omitted=next(p for p in bad if str(p) not in {e['path'] for e in s['errors']})
        with patch('os.scandir',side_effect=deny):unsafe=scan_capacity(self.root,safety_project=self.root,owner_roots=[*owners,omitted])
        self.assertTrue(scan_safety(unsafe,self.root,[*owners,omitted])[-1]['blocks_cleanup'])
        self.assertTrue(all(p.exists() for p in bad))
    def test_unknown_directory_not_assumed_safe(self):
        unknown=self.root/'manual';unknown.mkdir();self.assertTrue(scan_safety(self.scan(unknown),self.root,[self.root/'data'])[0]['blocks_cleanup'])
    def test_old_agent_capability_cannot_enable_new_validation_contract(self):
        f=NativeFixture(self.root/'fixture');self.addCleanup(f.close)
        class OldAgent:
            def query(self):return {'source':'TEST','capabilities':['DAILY_RETENTION_V1']}
            def command(self,p):raise AssertionError('old validation must not be trusted')
        m=MaintenanceService(ScopedStore(self.root/'system',boundary=self.root),f.advisory,OldAgent(),f.p,lambda:[],TradingCalendar())
        self.assertEqual(m.preview()['reason'],'AGENT_UPGRADE_REQUIRED')
    def test_reparse_and_truncated_identity_uncertainty_refuse(self):
        s=self.scan();s['errors'][0]['error']='REPARSE_POINT_NOT_FOLLOWED';self.assertTrue(scan_safety(s,self.root,[])[0]['blocks_cleanup'])
        s['errors']=[];s['errors_truncated']=True;self.assertTrue(scan_safety(s,self.root,[])[0]['blocks_cleanup'])
    def test_failed_scan_keeps_last_complete_and_shows_all_blockers(self):
        f=NativeFixture(self.root/'fixture');self.addCleanup(f.close)
        class Agent:
            root=None
            def query(self):return {'source':'TEST','capabilities':['DAILY_RETENTION_V1','RETENTION_VALIDATION_V2']}
            def command(self,p):return {'blocked':True,'reason':'NEW_DAY_OR_LOOKBACK_NOT_READY','validation':{'status':'FAILED','missing':[{'symbol':'bj920161','code':'DAILY_HISTORY_MISSING'}]}}
        m=MaintenanceService(ScopedStore(self.root/'system',boundary=self.root),f.advisory,Agent(),f.p,lambda:[],TradingCalendar(),inventory_root=self.root)
        first=m.run_once();last=first['last_complete_measurement'];original=os.scandir
        def deny(p):
            if Path(p)==self.bad:raise PermissionError('TEST')
            return original(p)
        with patch('os.scandir',side_effect=deny):r=m.run_once()
        self.assertEqual(r['capacity_scan']['status'],'PARTIAL');self.assertEqual(last,r['last_complete_measurement'])
        self.assertEqual(r['checks']['readiness']['status'],'FAILED');self.assertFalse(r['capacity_scan']['errors'][0]['blocks_cleanup']);self.assertFalse(m.policy['enabled'])

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(dir=ROOT/'tests',prefix='retention-upgrade-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'agent'
        self.now=datetime.fromisoformat('2026-09-10T15:20:00+08:00');self.cal=TradingCalendar();self.s=AgentService(self.root,clock=lambda:self.now,calendar=self.cal.is_open);self.addCleanup(lambda:self.s.close())
        self.s.command({'schema_version':'1.0','source':'TEST','action':'ADD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':0})
        self.s.cycle({'bj920161':frame(self.now)}) # Real schema, observations present, no volume baseline or READY.
    def restart(self,transport=False):
        self.s.close();original=subprocess.Popen
        def launch(args,*a,**kw):
            args=list(args)
            if str(args[1]).endswith('worker.mjs'):args[1]=str(ROOT/'tests/retention_worker_fixture.mjs')
            return original(args,*a,**kw)
        with patch('engines.live.market_agent.service.subprocess.Popen',side_effect=launch if transport else original):
            self.s=AgentService(self.root,clock=lambda:self.now,calendar=self.cal.is_open)
    def validate(self):return self.s.command({'schema_version':'1.0','source':'TEST','action':'RETENTION_VALIDATE','confirmation':'VALIDATE_NATIVE_BASELINES'})
    def test_empty_table_afternoon_upgrade_real_owner_native_prepare_succeeds(self):
        self.assertEqual(AgentRetention(self.s).validation()['status'],'FAILED')
        self.restart(True);self.assertTrue(AgentRetention(self.s).plan()['blocked'])
        before=len(self.s.repo.facts());v=self.validate();self.assertEqual(v['status'],'PASSED',v)
        self.assertFalse(AgentRetention(self.s).plan()['blocked']);self.assertEqual(before,len(self.s.repo.facts()))
        self.assertFalse((self.root/'retention-policy.json').exists())
    def test_normal_cycle_prepares_without_listener_or_policy(self):
        self.restart(True);self.s.cycle()
        self.assertFalse(AgentRetention(self.s).plan()['blocked']);self.assertEqual(self.s.query()['ai_calls'],0)
    def test_same_day_restart_restores_proof_and_samples_and_idempotent_cycle(self):
        self.restart(True);self.validate()
        with self.s.repo.connect() as db:proof=json.loads(db.execute('select payload from retention_readiness').fetchone()[0])
        self.restart(False);self.assertFalse(AgentRetention(self.s).plan()['blocked'])
        restored=self.s.worker.call({'op':'maintenance_baselines','day':self.now.date().isoformat()});self.assertEqual(proof['samples'],restored['samples'])
        before=self.s.repo.path.read_bytes();AgentRetention(self.s).prepare(self.now);self.assertEqual(before,self.s.repo.path.read_bytes())
    def test_missing_real_samples_fails_with_specific_reasons_and_get_no_write(self):
        self.restart();r=self.validate();self.assertEqual(r['status'],'FAILED');self.assertIn('VOLUME_HISTORY_MISSING',[m['code'] for m in r['missing']])
        before=self.s.repo.path.read_bytes()
        for _ in range(3):self.s.query();self.s.command({'schema_version':'1.0','source':'TEST','action':'RETENTION_PREVIEW'})
        self.assertEqual(before,self.s.repo.path.read_bytes())
    def test_new_day_rejects_old_proof_and_rest_day_uses_last_open_day(self):
        self.restart(True);self.validate();self.now+=timedelta(days=1);self.assertTrue(AgentRetention(self.s).plan()['blocked'])
        self.now=datetime.fromisoformat('2026-09-12T15:20:00+08:00');self.assertTrue(AgentRetention(self.s).plan()['blocked'])
        self.now=datetime.fromisoformat('2026-09-11T15:20:00+08:00')
        self.s.command({'schema_version':'1.0','source':'TEST','action':'BOARD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':self.s.repo.command_version()})
        self.s.cycle({'bj920161':frame(self.now)});value=self.validate();self.assertEqual(value['status'],'PASSED',value)
        self.now+=timedelta(days=1);self.assertFalse(AgentRetention(self.s).plan()['blocked'])
    def test_source_version_date_hash_mismatch_reject_old_proof(self):
        self.restart(True);self.validate()
        with self.s.repo.connect() as db:original=json.loads(db.execute('select payload from retention_readiness').fetchone()[0])
        for field,value in [('validation_version','obsolete'),('source','USER'),('root','other'),('generation','other')]:
            p=json.loads(json.dumps(original));p['identity'][field]=value
            with self.s.repo.connect() as db:db.execute('update retention_readiness set payload=?',(json.dumps(p),))
            self.assertTrue(AgentRetention(self.s).plan()['blocked'])
    def test_validation_interruption_retries_owner_commit(self):
        self.restart(True)
        with patch.object(self.s.worker,'call',side_effect=OSError('TEST INTERRUPT')):self.assertEqual(self.validate()['status'],'FAILED')
        self.assertEqual(self.validate()['status'],'PASSED')
    def test_weekend_restart_restores_latest_valid_scope_without_fetch(self):
        self.now=datetime.fromisoformat('2026-09-11T15:20:00+08:00')
        self.s.command({'schema_version':'1.0','source':'TEST','action':'BOARD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':self.s.repo.command_version()})
        self.s.cycle({'bj920161':frame(self.now)});self.restart(True);self.assertEqual(self.validate()['status'],'PASSED')
        self.now+=timedelta(days=1);self.s.cycle();self.restart(False)
        self.assertFalse(AgentRetention(self.s).plan()['blocked']);self.assertEqual(AgentRetention(self.s).validation()['status'],'PASSED')
    def test_reference_or_queued_task_after_preview_defers_before_delete(self):
        f=NativeFixture(Path(self.tmp.name)/'live');self.addCleanup(f.close);f.advisory.market_is_open=lambda _:True
        f.append();f.advisory.ingest();op=f.advisory.analyze('bj920161');self.restart(True);self.validate()
        refs=[];m=MaintenanceService(ScopedStore(Path(self.tmp.name)/'system',boundary=Path(self.tmp.name)),f.advisory,LocalPort(self.s),f.p,lambda:refs,self.cal)
        original=m.live.snapshot
        def changed(run):
            result=original(run);refs.append({'source_advisory_id':op['advisory_id']});return result
        m.policy['enabled']=True
        with patch.object(m.live,'snapshot',side_effect=changed):r=m.run_once(True)
        self.assertEqual(r['status'],'DEFERRED');self.assertIsNotNone(f.advisory.opinions.by_id(op['advisory_id']))
        self.assertEqual(r['blockers'][0]['code'],'MAINTENANCE_BOUNDARY_CHANGED')
        with f.advisory.runtime.connect() as db:db.execute("UPDATE live_analysis_requests SET status='QUEUED'")
        self.assertTrue(m.run_once()['pending']['blocked'])
    def test_complete_preview_validate_protect_backup_enable_clean(self):
        f=NativeFixture(Path(self.tmp.name)/'live');self.addCleanup(f.close);f.advisory.market_is_open=lambda _:True
        f.append();f.advisory.ingest();op=f.advisory.analyze('bj920161');account=f.create('ADVISORY_ONLY')
        intent={'symbol':'bj920161','portfolio_action':'OPEN','target_weight':.15,'source':'LIVE_AI_CONFIRMED','advisory_id':op['advisory_id'],'source_ref':op['advisory_id'],'advisory_session_date':op['session_date']}
        f.p.engine.submit(account['account_id'],intent,quote(time=f.now.isoformat()),f.now.isoformat())
        # A second unreferenced old opinion is eligible; account evidence remains self-contained.
        f.append();discard=f.advisory.analyze('bj920161');ledger=f.p.engine.ledger(account['account_id']);state=f.p.engine.state(account['account_id']);cursor=f.advisory.runtime.cursor(op['tracking_session_id'])
        self.now=datetime.fromisoformat('2026-09-11T10:35:00+08:00')
        self.s.command({'schema_version':'1.0','source':'TEST','action':'BOARD','symbol':'bj920161','name':'测试','board':{'code':'BKTEST','name':'测试'},'command_id':uuid.uuid4().hex,'expected_version':self.s.repo.command_version()})
        self.s.cycle({'bj920161':frame(self.now)})
        f.now=self.now;f.members={};f.add_symbol('bj920161','测试甲');f.append();f.advisory.ingest();today=f.advisory.analyze('bj920161')
        m=MaintenanceService(ScopedStore(Path(self.tmp.name)/'system',boundary=Path(self.tmp.name)),f.advisory,LocalPort(self.s),f.p,lambda:[],self.cal)
        self.assertTrue(m.run_once()['pending']['blocked']);self.restart(True);m.agent=LocalPort(self.s);self.assertEqual(self.validate()['status'],'PASSED')
        self.assertFalse(m.run_once()['pending']['blocked']);self.assertIsNotNone(f.advisory.opinions.by_id(discard['advisory_id']))
        m.request('enable',{'confirmation':'ENABLE_LATEST_READY_DAY_RETENTION'});result=m.run_once(True);self.assertEqual(result['status'],'DONE',result)
        self.assertIsNone(f.advisory.opinions.by_id(discard['advisory_id']));self.assertIsNotNone(f.advisory.opinions.by_id(op['advisory_id']))
        self.assertEqual(ledger,f.p.engine.ledger(account['account_id']));self.assertEqual(state,f.p.engine.state(account['account_id']));self.assertEqual(cursor,f.advisory.runtime.cursor(op['tracking_session_id']))
        self.assertEqual(result['checks']['snapshots'],'VERIFIED');self.assertFalse(AgentRetention(self.s).plan()['blocked'])
        self.assertEqual(m.run_once()['checks']['snapshots'],'VERIFIED','new read-only preview must recognize already verified current-run snapshots')
        self.assertIsNotNone(f.advisory.opinions.by_id(today['advisory_id']))
        self.assertTrue(all(x['payload'].get('session_date',x['payload'].get('date','2026-09-11'))>='2026-09-11' for x in self.s.repo.facts() if x['kind'] in ('SESSION','OBSERVATION','EVENT','SNAPSHOT')))
        with f.p.engine.repository.transaction(account['account_id']) as db:self.assertEqual(db.execute('select count(*) from retained_advisory_evidence').fetchone()[0],1)

if __name__=='__main__':unittest.main()
