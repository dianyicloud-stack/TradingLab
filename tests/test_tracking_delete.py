"""Deletion requires the owner; isolated Agent/Live stores only."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from threading import Thread,Event
import tempfile,unittest,uuid,json
from unittest.mock import patch
from engines.live.market_agent.service import AgentService
from engines.live.advisory_repository import AdvisoryRuntimeRepository,AdvisoryOpinionRepository
from app.live.tracking_delete import LiveTrackingDeletion
from shared.config import ScopedStore
from contracts.live.market_agent import AgentError
from tests.test_market_agent import LocalPort,frame
from tests.support.native import NativeFixture

class TrackingDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='delete-test-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=datetime(2026,9,17,9,35,40,tzinfo=timezone(timedelta(hours=8)))
        self.service=AgentService(self.root/'agent',clock=lambda:self.now,calendar=lambda _:True);self.addCleanup(lambda:self.service.close())
        self.port=LocalPort(self.service)
        store=ScopedStore(self.root/'live',boundary=self.root)
        self.advisory=SimpleNamespace(runtime=AdvisoryRuntimeRepository(store.child('runtime')),opinions=AdvisoryOpinionRepository(store.child('opinions')))
        self.deletion=LiveTrackingDeletion(self.port,self.advisory,lambda _:[])
        for symbol in ('bj920161','sh688601'):self.cmd('ADD',symbol,name='test',board={'code':'BKTEST','name':'test'})
        self.service.cycle({s:frame(self.now) for s in ('bj920161','sh688601')})
    def cmd(self,action,symbol='bj920161',**extra):
        return self.service.command({'schema_version':'1.0','source':'TEST','command_id':str(uuid.uuid4()),'expected_version':self.service.query()['version'],'action':action,'symbol':symbol,**extra})
    def delete(self):return self.deletion.delete({'symbol':'bj920161','source':'TEST','confirmation':'DELETE_TRACKING_DATA'})
    def test_delete_owner_facts_live_preferences_and_idempotent(self):
        sid=next(s['tracking_session_id'] for s in self.service.query()['sessions'] if s['symbol']=='bj920161')
        self.advisory.runtime.save_preferences('bj920161',{'visible':False,'pinned':True})
        self.cmd('STOP');result=self.delete()
        self.assertEqual(result['status'],'DELETED');self.assertTrue(Path(result['backup'],'manifest.json').is_file())
        self.assertEqual(self.advisory.runtime.preferences('bj920161'),{})
        self.assertTrue(self.advisory.runtime.retired(sid));self.assertFalse(any(s['symbol']=='bj920161' for s in self.service.query()['sessions']))
        self.assertFalse(any(r['payload'].get('tracking_session_id')==sid for r in self.service.repo.facts()))
        self.assertTrue(any(s['symbol']=='sh688601' for s in self.service.query()['sessions']))
        self.assertTrue(self.delete()['idempotent'])
    def test_restart_and_readd_new_lifecycle(self):
        old=next(s['tracking_session_id'] for s in self.service.query()['sessions'] if s['symbol']=='bj920161')
        self.delete();self.service.close();self.service=AgentService(self.root/'agent',clock=lambda:self.now,calendar=lambda _:True);self.port.service=self.service
        self.assertFalse(any(s['symbol']=='bj920161' for s in self.service.query()['sessions']))
        self.cmd('ADD',name='again',board={'code':'BKTEST','name':'test'})
        new=next(s['tracking_session_id'] for s in self.service.query()['sessions'] if s['symbol']=='bj920161')
        self.assertNotEqual(old,new);self.assertFalse(self.advisory.runtime.retired(new))
        self.assertFalse([f for f in self.service.repo.facts('EVENT') if f['payload'].get('tracking_session_id')==old])
    def test_protected_opinion_evidence_archived_not_cascaded(self):
        sid=next(s['tracking_session_id'] for s in self.service.query()['sessions'] if s['symbol']=='bj920161')
        f={'input_id':'i','input_hash':'h','created_at':self.now.isoformat()};op={'advisory_id':'o','input_id':'i','symbol':'bj920161','tracking_session_id':sid,'session_date':'2026-09-17','generated_at':self.now.isoformat()}
        self.advisory.opinions.append(f,op);result=self.delete()
        self.assertTrue(result['protected']);self.assertEqual(self.advisory.opinions.by_id('o'),op)
        with self.service.repo.connect() as db:self.assertGreater(db.execute('SELECT count(*) FROM protected_tracking_facts').fetchone()[0],0)
    def test_crash_after_owner_commit_retry_finishes_live(self):
        with patch.object(self.advisory.runtime,'finish_tracking_deletion',side_effect=OSError('test crash')):
            with self.assertRaises(OSError):self.delete()
        self.assertEqual(self.advisory.runtime.deletion_intent('bj920161')['status'],'PENDING')
        self.assertEqual(self.delete()['status'],'DELETED');self.assertEqual(self.advisory.runtime.deletion_intent('bj920161')['status'],'DELETED')
    def test_old_owner_rejected_without_hiding(self):
        query=self.port.query
        with patch.object(self.port,'query',side_effect=lambda:{k:v for k,v in query().items() if k!='capabilities'}):
            with self.assertRaises(AgentError) as caught:self.delete()
        self.assertEqual(caught.exception.code,'AGENT_DELETE_UPGRADE_REQUIRED')
        self.assertIsNone(self.advisory.runtime.deletion_intent('bj920161'));self.assertTrue(any(s['symbol']=='bj920161' for s in self.service.query()['sessions']))
    def test_account_references_conservative(self):
        self.deletion.account_refs=lambda _:['ACCOUNT:existing']
        result=self.delete();self.assertTrue(result['protected']);self.assertTrue(all('ACCOUNT:existing' in refs for refs in result['protected_references'].values()))
    def test_old_read_model_filtered_during_refresh(self):
        old=self.service.query();self.delete();view=self.deletion.filter_current(old)
        self.assertFalse(any(s['symbol']=='bj920161' for s in view['sessions']))
    def test_retired_records_cannot_be_reinserted(self):
        old=self.service.repo.checkpoint()[1];records=self.service._session_records(old);self.delete()
        self.service.repo.commit(old,records);self.service._publish()
        self.assertFalse(any(s['symbol']=='bj920161' for s in self.service.query()['sessions']))

class DeletedInFlightTests(unittest.TestCase):
    def test_inflight_result_retained_without_cursor_or_execution(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            f=NativeFixture(Path(tmp))
            try:
                f.create('AUTO_SHADOW_EXECUTION');f.append();sid=f.members['bj920161']['tracking_session_id']
                entered=Event();release=Event();original=f.provider.analyze;result=[]
                def paused(*a,**k):entered.set();release.wait(10);return original(*a,**k)
                with patch.object(f.provider,'analyze',side_effect=paused):
                    t=Thread(target=lambda:result.append(f.advisory.analyze('bj920161')));t.start();self.assertTrue(entered.wait(5))
                    f.advisory.runtime.begin_tracking_deletion('bj920161',[sid],{'command_id':'test-delete'})
                    release.set();t.join(10)
                self.assertEqual(len(result),1);self.assertFalse(result[0]['effective_result']);self.assertIsNone(f.advisory.runtime.cursor(sid))
                self.assertEqual(f.advisory.runtime.portfolio_outcome(result[0]['advisory_id'])['reason'],'SUPERSEDED_ANALYSIS')
            finally:f.close()

if __name__=='__main__':unittest.main()
