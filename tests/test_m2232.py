from datetime import timedelta
import hashlib,json,tempfile,time,unittest
from pathlib import Path
from threading import Event,Thread
from contracts.live.bridge import BridgeError
from tests.support.native import NativeFixture

ROOT=Path(__file__).resolve().parents[1]

class LiveNativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='m2232-',dir=ROOT/'tests');self.addCleanup(self.tmp.cleanup)
        self.f=NativeFixture(Path(self.tmp.name));self.addCleanup(self.f.close);self.s=self.f.advisory
    def wait(self,fn):
        for _ in range(100):
            if fn():return
            time.sleep(.03)
        self.fail('listener condition timed out')
    def test_discovery_without_handoff(self):
        self.assertEqual(len(self.s.current_facts()),2)
        self.assertFalse(hasattr(self.f.bridge,'handoff_documents'))
    def test_listener_append_without_restart(self):
        self.f.app.live_loop.start();self.f.append()
        identity=self.f.members['bj920161']['tracking_session_id']
        self.wait(lambda:self.s.runtime.ingestion(identity).get('listener_event_cursor')==1)
        self.f.append();self.wait(lambda:self.s.runtime.ingestion(identity).get('listener_event_cursor')==2)
        self.assertEqual(len(self.s.runtime.ingested_facts(identity,'EVENT')),2)
        self.assertEqual(len(self.s.runtime.ingested_facts(identity,'OBSERVATION')),2)
    def test_ingestion_deduplicated_after_restart(self):
        self.f.append();self.s.ingest();self.s.ingest()
        identity=self.f.members['bj920161']['tracking_session_id']
        self.assertEqual(len(self.s.runtime.ingested_facts(identity,'EVENT')),1)
    def test_native_semantics(self):
        self.f.append();event=self.s.stock_cards()[0]['events'][0]
        for key in ('event_seq','tracking_session_id','symbol','price','severity'):
            self.assertEqual(event[key],self.f.native_events[0][key])
        self.assertEqual(event['source'],'V2A_NATIVE');self.assertEqual(event['native_source'],'tracker_5m')
    def test_event_only_does_not_fabricate_observation(self):
        self.f.append(observation=False);opinion=self.s.analyze('bj920161')
        frozen=self.s.bundle(opinion['advisory_id'])[1]
        self.assertEqual(frozen['incremental_evidence']['observations'],[])
        self.assertIsNone(self.s.runtime.cursor(opinion['tracking_session_id'])['last_advised_observation_time'])
        with self.assertRaises(BridgeError) as e:self.s.analyze('bj920161')
        self.assertEqual(e.exception.code,'NO_NEW_ADVISORY_DATA')
    def test_two_symbol_frozen_context_isolated(self):
        for symbol in self.f.members:self.f.append(symbol);self.s.analyze(symbol)
        for call in self.f.provider.calls:
            frozen=call['frozen'];self.assertIsNone(frozen['previous_advisory'])
            self.assertTrue(all(e['symbol']==frozen['symbol'] for e in frozen['incremental_evidence']['events']))
    def test_daily_session_resets_previous_and_cursor(self):
        self.f.append();old=self.s.analyze('bj920161');self.f.now+=timedelta(days=1)
        new=self.f.add_symbol('bj920161','测试甲');self.f.append()
        value=self.s.analyze('bj920161');frozen=self.s.bundle(value['advisory_id'])[1]
        self.assertNotEqual(old['tracking_session_id'],new);self.assertIsNone(frozen['previous_advisory'])
        self.assertEqual(value['data_through_event_seq'],1)
    def test_hide_does_not_stop_ingestion(self):
        self.s.preferences('bj920161',{'visible':False});self.f.append();self.s.ingest()
        self.assertEqual(self.s.runtime.ingestion(self.f.members['bj920161']['tracking_session_id'])['listener_event_cursor'],1)
        self.assertFalse(next(c for c in self.s.stock_cards() if c['session']['symbol']=='bj920161')['settings']['visible'])
        self.s.preferences('bj920161',{'visible':True});self.assertEqual(len(self.s.stock_cards()[0]['events']),1)
    def test_preferences_persist_and_reject_unknown_type(self):
        self.s.preferences('bj920161',{'pinned':True,'visible':False})
        self.assertEqual(self.s.runtime.preferences('bj920161'),{'pinned':True,'visible':False})
        with self.assertRaises(BridgeError):self.s.preferences('bj920161',{'auto_event_types':['INVENTED']})
    def test_auto_a_only_b_manual(self):
        self.s.preferences('bj920161',{'auto_ai_mode':'ALL_EVENTS'})
        for symbol in self.f.members:self.f.append(symbol)
        self.s.poll_auto();self.f.now+=timedelta(seconds=4);self.s.poll_auto()
        self.assertEqual([x['frozen']['symbol'] for x in self.f.provider.calls],['bj920161'])
        self.s.analyze('sh688696');self.assertEqual(self.f.provider.calls[-1]['frozen']['symbol'],'sh688696')
    def test_event_type_allowlist(self):
        self.f.append();self.s.analyze('bj920161')
        self.s.preferences('bj920161',{'auto_ai_mode':'ALL_EVENTS','auto_event_types':['NEW_HIGH']})
        self.f.append(kind='PRICE_UPDATE');self.s.poll_auto();self.f.now+=timedelta(seconds=4);self.s.poll_auto()
        self.assertEqual(len(self.f.provider.calls),1)
        self.f.append();self.s.poll_auto();self.f.now+=timedelta(seconds=4);self.s.poll_auto();self.assertEqual(len(self.f.provider.calls),2)
    def test_important_uses_level(self):
        self.assertTrue(self.s._important([{'type':'UNCLASSIFIED','level':'CRITICAL'}],{}))
    def test_manual_new_observation_without_event(self):
        self.f.append();self.s.analyze('bj920161');self.f.append(event=False)
        opinion=self.s.analyze('bj920161');frozen=self.s.bundle(opinion['advisory_id'])[1]
        self.assertEqual(frozen['incremental_evidence']['events'],[])
        self.assertEqual(len(frozen['incremental_evidence']['observations']),1)
    def test_manual_reanalysis_explicit(self):
        self.f.append();self.s.analyze('bj920161')
        with self.assertRaises(BridgeError):self.s.analyze('bj920161')
        self.assertEqual(self.s.analyze('bj920161',force=True)['trigger_type'],'MANUAL_REANALYSIS')
    def test_provider_failure_preserves_success(self):
        self.f.append();first=self.s.analyze('bj920161');self.f.append()
        self.f.provider.callback=lambda:(_ for _ in ()).throw(RuntimeError('TEST timeout'))
        with self.assertRaises(BridgeError):self.s.analyze('bj920161')
        self.assertEqual(self.s.latest('bj920161')['advisory_id'],first['advisory_id'])
        self.assertIsNotNone(self.s.symbol_health('bj920161')['last_failure'])
    def test_multi_symbol_concurrency_same_symbol_serial(self):
        for symbol in self.f.members:self.f.append(symbol)
        entered=Event();release=Event()
        def callback():
            if len(self.f.provider.calls)>=2:entered.set()
            release.wait(3)
        self.f.provider.callback=callback
        threads=[Thread(target=self.s.analyze,args=(s,)) for s in self.f.members]
        for t in threads:t.start()
        self.assertTrue(entered.wait(2));self.assertEqual(self.s.analyze('bj920161')['status'],'PENDING_AGGREGATION')
        release.set()
        for t in threads:t.join(3)
        self.assertEqual(len(self.f.provider.calls),2)
    def test_listener_consumes_during_slow_ai(self):
        self.f.append();self.s.preferences('bj920161',{'auto_ai_mode':'ALL_EVENTS'});self.s.poll_auto();self.f.now+=timedelta(seconds=4)
        started=Event();release=Event()
        self.f.provider.callback=lambda:(started.set(),release.wait(3))
        self.f.app.live_loop.start();self.assertTrue(started.wait(2));self.f.append()
        identity=self.f.members['bj920161']['tracking_session_id']
        self.wait(lambda:self.s.runtime.ingestion(identity).get('listener_event_cursor')==2)
        release.set()
    def test_stopped_tracking_does_not_auto_analyze(self):
        self.f.append();self.f.members['bj920161']['lifecycle_status']='STOPPED';self.f.publish()
        self.s.preferences('bj920161',{'auto_ai_mode':'ALL_EVENTS'});self.s.poll_auto();self.f.now+=timedelta(seconds=4);self.s.poll_auto()
        self.assertFalse(self.f.provider.calls);self.assertEqual(len(self.s.stock_cards()[0]['events']),1)
    def test_workspace_readonly(self):
        self.f.append();before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.f.workspace.iterdir() if p.is_file()}
        self.s.ingest();self.s.stock_cards();self.s.analyze('bj920161')
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.f.workspace.iterdir() if p.is_file()})
    def test_formal_product_removed(self):
        live=(ROOT/'app/live/templates/live.html').read_text(encoding='utf-8')
        self.assertNotIn('ACK',live);self.assertNotIn('formal-decision-section',live)
        self.assertFalse((ROOT/'app/live/templates/formal.html').exists())
    def test_bad_optional_handoff_cannot_block_native_facts(self):
        self.f.append();(self.f.workspace/'ai_handoff.json').write_text('{partial',encoding='utf-8')
        self.assertEqual(self.s.analyze('bj920161')['data_through_event_seq'],1)
    def test_metadata_fallback_without_frontend_names(self):
        self.f.members['bj920161'].pop('name');self.f.publish()
        self.s.stock_metadata=lambda symbol:{'instrument_name':'TEST metadata'}
        self.assertEqual(self.s._member('bj920161')[1]['name'],'TEST metadata')
    def test_same_session_restart_preserves_advisory_cursor(self):
        self.f.append();first=self.s.analyze('bj920161');self.f.publish()
        with self.assertRaises(BridgeError):self.s.analyze('bj920161')
        self.assertEqual(self.s.latest('bj920161')['advisory_id'],first['advisory_id'])
    def test_new_stock_discovered_after_service_start(self):
        self.f.add_symbol('sz000001','测试丙');self.f.publish();self.s.ingest()
        self.assertEqual(len(self.s.stock_cards()),3)
    def test_history_only_same_current_session(self):
        self.f.append();self.s.analyze('bj920161');self.f.now+=timedelta(days=1)
        self.f.add_symbol('bj920161','测试甲');self.f.append();self.s.analyze('bj920161')
        self.assertEqual(len(self.s.history('bj920161')),1)
    def test_runtime_snapshots_retained_for_next_incremental_window(self):
        identity=self.f.members['bj920161']['tracking_session_id']
        for minute in (30,35,40):
            # The clock must reach the sample before a frozen prompt can use it.
            self.f.now=self.f.now.replace(minute=minute,second=0)
            current={'tracking_session_id':identity,'price':10,'timestamp':f'2026-09-09T10:{minute}:00+08:00'}
            self.f.native_observations.append({**current,'symbol':'bj920161','source_format':'V2A_RUNTIME_STATE'});self.f.publish()
            self.s.ingest()
        frozen=self.s.freeze('bj920161','MANUAL')
        self.assertEqual(len(frozen['incremental_evidence']['observations']),3)
    def test_sync_lag_does_not_claim_fresh(self):
        self.f.append();self.s.ingest();self.f.append()
        sync=next(c for c in self.s.stock_cards() if c['session']['symbol']=='bj920161')['sync']
        self.assertEqual(sync['status'],'LAGGING');self.assertEqual(sync['lag_seconds'],10)
    def test_auto_failure_does_not_repeat_same_input_forever(self):
        self.f.append();self.s.preferences('bj920161',{'auto_ai_mode':'ALL_EVENTS'})
        self.f.provider.callback=lambda:(_ for _ in ()).throw(RuntimeError('TEST failure'))
        self.s.poll_auto();self.f.now+=timedelta(seconds=4)
        with self.assertRaises(BridgeError):self.s.poll_auto()
        self.s.poll_auto();self.assertEqual(len(self.f.provider.calls),1)
