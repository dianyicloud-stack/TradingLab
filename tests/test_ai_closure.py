"""Second closure: isolated facts and fake AI; no production calls or writes."""
from pathlib import Path
from datetime import timedelta
from threading import Event,Thread
from unittest.mock import patch
import tempfile,time,unittest,json,subprocess
from types import SimpleNamespace
from contracts.live.bridge import BridgeError
from tests.support.native import NativeFixture

ROOT=Path(__file__).resolve().parents[1]

class AIClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ai-closure-',dir=ROOT/'tests')
        self.addCleanup(self.tmp.cleanup)
        self.f=NativeFixture(Path(self.tmp.name));self.addCleanup(self.f.close)
        self.a=self.f.advisory;self.symbol='bj920161';self.f.append()
        self.sid=self.f.members[self.symbol]['tracking_session_id']
        self.a.market_is_open=lambda day:True
    def status(self):return self.a.symbol_health(self.symbol)['analysis_status']
    def wait(self,fn):
        for _ in range(150):
            if fn():return
            time.sleep(.02)
        self.fail('task did not finish')
    def test_manual_trading_success_status(self):
        o=self.a.analyze(self.symbol);s=self.status()
        self.assertEqual(s['current_task']['state'],'SUCCEEDED')
        self.assertEqual(s['latest_successful_analysis']['opinion_id'],o['advisory_id'])
        self.assertFalse(s['pending']['has_new_data'])
    def test_manual_lunch_uses_last_trusted_facts(self):
        self.f.now=self.f.now.replace(hour=11,minute=29,second=50);self.f.append()
        self.f.now=self.f.now.replace(hour=12,minute=15)
        o=self.a.analyze(self.symbol)
        self.assertIn('11:30',o['data_through_at']);self.assertIn('04:15',o['ai_completed_at'])
    def test_manual_after_close_uses_last_trusted_facts(self):
        self.f.now=self.f.now.replace(hour=14,minute=59,second=50);self.f.append()
        self.f.now=self.f.now.replace(hour=15,minute=6)
        o=self.a.analyze(self.symbol)
        self.assertIn('15:00',o['data_through_at']);self.assertEqual(o['trigger_type'],'MANUAL')
    def test_no_new_is_not_failed_and_force_is_explicit(self):
        first=self.a.analyze(self.symbol)
        with self.assertRaises(BridgeError) as caught:self.a.analyze(self.symbol)
        self.assertEqual(caught.exception.code,'NO_NEW_ADVISORY_DATA')
        self.assertIsNone(self.status()['failure']);self.assertEqual(self.status()['current_task']['state'],'NO_NEW_DATA')
        self.assertEqual(len(self.f.provider.calls),1)
        second=self.a.analyze(self.symbol,force=True)
        self.assertEqual(second['trigger_type'],'MANUAL_REANALYSIS');self.assertNotEqual(first['advisory_id'],second['advisory_id'])
    def test_timeout_keeps_success_cursor_and_new_data(self):
        o=self.a.analyze(self.symbol);cursor=self.a.runtime.cursor(self.sid);self.f.append()
        original=self.f.provider.analyze
        with patch.object(self.f.provider,'analyze',side_effect=TimeoutError('sensitive prompt must not persist')):
            with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        s=self.status();self.assertEqual(s['failure']['error_code'],'PROVIDER_TIMEOUT')
        self.assertEqual(s['failure']['stage'],'PROVIDER');self.assertTrue(s['failure']['retryable'])
        self.assertEqual(self.a.latest(self.symbol)['advisory_id'],o['advisory_id'])
        self.assertEqual(self.a.runtime.cursor(self.sid),cursor);self.assertTrue(s['pending']['has_new_data'])
        self.assertNotIn('sensitive',str(self.a.runtime.latest_failure(self.sid)))
        self.a.analyze(self.symbol);self.assertIsNone(self.status()['failure'])
    def test_input_failure_recorded_without_provider(self):
        with patch.object(self.a,'freeze',side_effect=BridgeError('ADVISORY_FUTURE_DATA')):
            with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        self.assertFalse(self.f.provider.calls)
        self.assertEqual(self.status()['failure']['stage'],'INPUT')
    def test_persistence_failure_does_not_advance_or_delete(self):
        o=self.a.analyze(self.symbol);cursor=self.a.runtime.cursor(self.sid);self.f.append()
        with patch.object(self.a.opinions,'append',side_effect=OSError('private path')):
            with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        self.assertEqual(self.status()['failure']['error_code'],'PERSISTENCE_FAILED')
        self.assertEqual(self.a.latest(self.symbol)['advisory_id'],o['advisory_id']);self.assertEqual(self.a.runtime.cursor(self.sid),cursor)

    def test_upstream_400_preserves_task_and_exposes_safe_failure_without_opinion_or_trade(self):
        from app.live.router import LiveRouter
        from contracts.live.advisory import AdvisoryProviderFailure
        account=self.f.create('ADVISORY_ONLY')
        first=self.a.analyze(self.symbol);cursor=self.a.runtime.cursor(self.sid)
        ledger=self.f.p.engine.ledger(account['account_id']);self.f.append()
        failure=AdvisoryProviderFailure({'stage':'PROVIDER','error_code':'MODEL_INVALID',
            'http_status':400,'retryable':False,'provider_invoked':True,
            'provider_attempt_count':1,'transport_exception_type':'BadRequestError'})
        with patch.object(self.f.provider,'analyze',side_effect=failure):
            status,body,_=LiveRouter(self.f.app.live_loop).route('POST','/api/live/bj920161/analyze',{'mode':'NORMAL'})
        self.assertEqual(status,502);self.assertEqual(body['error'],'ADVISORY_PROVIDER_ERROR')
        self.assertEqual(body['failure']['http_status'],400)
        self.assertEqual(body['failure']['error_code'],'MODEL_INVALID')
        self.assertEqual(body['failure']['provider_attempt_count'],1)
        self.assertEqual(body['failure']['transport_exception_type'],'BadRequestError')
        task=self.status()['current_task'];self.assertEqual(task['state'],'FAILED')
        self.assertEqual(body['failure']['task_id'],task['task_id'])
        self.assertEqual(self.a.latest(self.symbol)['advisory_id'],first['advisory_id'])
        self.assertEqual(self.a.runtime.cursor(self.sid),cursor)
        self.assertEqual(self.f.p.engine.ledger(account['account_id']),ledger)
    def test_saved_opinion_runtime_failure_retry_never_recharges_or_executes(self):
        with patch.object(self.a.runtime,'commit_success',side_effect=OSError('disk unavailable')):
            with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        saved=self.a.latest(self.symbol);self.assertIsNone(self.a.runtime.cursor(self.sid))
        with patch.object(self.a,'portfolio_result') as account:
            recovered=self.a.analyze(self.symbol)
            account.assert_not_called()
        self.assertEqual(recovered['advisory_id'],saved['advisory_id']);self.assertEqual(len(self.f.provider.calls),1)
        self.assertEqual(self.a.runtime.cursor(self.sid)['last_advisory_id'],saved['advisory_id'])
        self.assertEqual(self.a.runtime.latest_failure(self.sid)['request_id'],saved['request_id'])
    def test_success_markers_rollback_as_one_transaction(self):
        with self.a.runtime.connect() as db:
            db.execute("CREATE TRIGGER test_cursor_fail BEFORE INSERT ON advisory_cursors BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        for kind in ('EVALUATION_CONTEXT','ADVISED_RECORDS','ADVISED_TRIGGERS'):
            self.assertIsNone(self.a.runtime.native_control(self.sid,kind))
        self.assertIsNone(self.a.runtime.cursor(self.sid))
    def test_diagnostics_bounded_opt_in_and_no_sensitive_payload(self):
        from engines.live.analysis_diagnostics import AnalysisDiagnostics
        disabled=AnalysisDiagnostics();disabled.record(stage='INPUT');self.assertFalse(disabled.rows)
        enabled=AnalysisDiagnostics(enabled=True)
        for i in range(300):enabled.record(task_id=str(i),stage='PROVIDER',prompt='secret',frozen={'secret':1},api_key='secret')
        self.assertEqual(len(enabled.rows),128);self.assertNotIn('secret',str(enabled.rows))
    def test_listener_stop_explained_separately_from_qualifying_event_count(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS'})
        self.assertEqual(self.f.app.live_loop.status,'STOPPED')
        s=self.status();self.assertIn('LISTENER_STOPPED',s['eligibility']['blockers'])
        self.assertEqual(s['pending']['eligible_event_count'],1);self.assertFalse(s['eligibility']['eligible'])
    def test_empty_filter_is_explained_without_changing_settings(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS','auto_event_types':[]})
        s=self.status();self.assertEqual(s['pending']['eligible_event_count'],0)
        self.assertIn('EVENT_FILTER_EMPTY',s['eligibility']['blockers'])
        self.assertEqual(s['pending']['new_event_count'],1)
        self.a.poll_auto();self.f.now+=timedelta(seconds=5);self.a.poll_auto();self.assertFalse(self.f.provider.calls)
    def test_important_rule_filters_each_event(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'IMPORTANT_ONLY'})
        self.f.append(kind='INFO');s=self.status()
        self.assertEqual(s['pending']['new_event_count'],2);self.assertEqual(s['pending']['eligible_event_count'],1)
    def test_off_and_per_symbol_override(self):
        self.a.save_settings({'auto_ai_mode':'OFF'});self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS'})
        self.f.append('sh688696')
        self.assertEqual(self.status()['pending']['eligible_event_count'],1)
        self.assertIn('AUTO_OFF',self.a.symbol_health('sh688696')['analysis_status']['eligibility']['blockers'])
    def test_read_cursor_is_independent_and_status_readonly(self):
        o=self.a.analyze(self.symbol);cursor=self.a.runtime.cursor(self.sid)
        self.a.mark_read(self.symbol,{'tracking_session_id':self.sid,'advisory_id':o['advisory_id'],'event_seq':1})
        for _ in range(3):self.status()
        self.assertEqual(self.a.runtime.cursor(self.sid),cursor);self.assertEqual(len(self.f.provider.calls),1)
        self.assertEqual(self.status()['pending']['unread_event_count'],0)
    def test_duplicate_running_force_coalesces(self):
        entered,release=Event(),Event();original=self.f.provider.analyze;errors=[]
        def slow(*a):entered.set();release.wait(4);return original(*a)
        self.f.provider.analyze=slow
        def run():
            try:self.a.analyze(self.symbol,force=True)
            except Exception as e:errors.append(e)
        t=Thread(target=run);t.start();self.assertTrue(entered.wait(2))
        queued=self.a.analyze(self.symbol,force=True);self.assertTrue(queued['queued'])
        release.set();t.join(5);self.wait(lambda:not self.a.runtime.has_running_work())
        self.assertFalse(errors);self.assertEqual(len(self.f.provider.calls),1)
    def test_auto_manual_same_window_coalesces(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS'})
        entered,release=Event(),Event();original=self.f.provider.analyze
        def slow(*a):entered.set();release.wait(4);return original(*a)
        self.f.provider.analyze=slow
        t=Thread(target=lambda:self.a.analyze(self.symbol,trigger_type='AUTO_EVENT'));t.start();self.assertTrue(entered.wait(2))
        self.a.analyze(self.symbol);release.set();t.join(5)
        self.wait(lambda:not self.a.runtime.has_running_work());self.assertEqual(len(self.f.provider.calls),1)

    def test_many_events_debounce_and_same_event_never_repeats(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS'})
        self.a.save_settings({'debounce_seconds':3})
        self.f.append();self.f.append();self.a.poll_auto()
        self.f.now+=timedelta(seconds=4);self.a.poll_auto()
        self.assertEqual(len(self.f.provider.calls),1)
        self.a.poll_auto();self.f.now+=timedelta(seconds=4);self.a.poll_auto()
        self.assertEqual(len(self.f.provider.calls),1)
    def test_during_analysis_new_events_preserve_input_and_enter_next_window(self):
        self.a.preferences(self.symbol,{'auto_ai_mode':'ALL_EVENTS'});self.a.save_settings({'debounce_seconds':3})
        entered,release=Event(),Event();original=self.f.provider.analyze;frozen_seen=[]
        def slow(frozen,*args):
            frozen_seen.append(json.dumps(frozen,sort_keys=True));entered.set();release.wait(4)
            self.assertEqual(json.dumps(frozen,sort_keys=True),frozen_seen[0]);return original(frozen,*args)
        with patch.object(self.f.provider,'analyze',side_effect=slow):
            t=Thread(target=lambda:self.a.analyze(self.symbol));t.start();self.assertTrue(entered.wait(2))
            self.f.append();self.a.poll_auto();release.set();t.join(5)
        self.a.poll_auto();self.f.now+=timedelta(seconds=4);self.a.poll_auto()
        self.assertEqual(len(self.f.provider.calls),2)
        self.assertEqual(json.loads(frozen_seen[0])['data_through_event_seq'],1)
        self.assertEqual(self.a.latest(self.symbol)['data_through_event_seq'],2)
    def test_historical_task_without_metadata_is_readable_and_unclassified(self):
        o=self.a.analyze(self.symbol)
        with self.a.runtime.connect() as db:
            db.execute("UPDATE live_analysis_requests SET payload=json_remove(payload,'$.task'),status='FAILED'")
        s=self.status();self.assertEqual(s['failure']['error_code'],'HISTORICAL_FAILURE_UNCLASSIFIED')
        self.assertEqual(s['latest_successful_analysis']['opinion_id'],o['advisory_id'])
    def test_network_and_schema_failures_classified_without_advancing(self):
        for error,code in ((ConnectionError('private endpoint'),'PROVIDER_NETWORK_ERROR'),
                           (json.JSONDecodeError('private body','secret',0),'PROVIDER_PARSE_ERROR')):
            with self.subTest(code=code):
                with patch.object(self.f.provider,'analyze',side_effect=error):
                    with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
                self.assertEqual(self.status()['failure']['error_code'],code);self.assertIsNone(self.a.runtime.cursor(self.sid))
        with patch.object(self.f.provider,'analyze',return_value={'analysis':{}}):
            with self.assertRaises(BridgeError):self.a.analyze(self.symbol)
        self.assertEqual(self.status()['failure']['error_code'],'PROVIDER_SCHEMA_ERROR')

class TransportDiagnosticsTests(unittest.TestCase):
    def test_worker_keeps_only_safe_exception_shape(self):
        from adapters.ai.worker import safe_exception_details
        class BadRequestError(Exception):pass
        error=RuntimeError('private provider response')
        error.__cause__=BadRequestError('private body')
        error.usage_records=[{'raw_response':'private body'}]
        details=safe_exception_details(error)
        self.assertEqual(details,{'provider_attempt_count':1,'transport_exception_type':'BadRequestError'})
        self.assertNotIn('private',str(details))

    def test_transport_failure_categories_without_executing_worker(self):
        from adapters.ai.transport import ProviderTransport
        from contracts.live.advisory import AdvisoryProviderFailure
        for status,expected,stage in [('TIMEOUT','PROVIDER_TIMEOUT','PROVIDER'),('NETWORK_ERROR','PROVIDER_NETWORK_ERROR','PROVIDER'),
                                     ('HTTP_ERROR','PROVIDER_HTTP_ERROR','PROVIDER'),('INVALID_RESPONSE','PROVIDER_PARSE_ERROR','PROVIDER'),
                                     ('SCHEMA_VALIDATION_FAILED','PROVIDER_SCHEMA_ERROR','SCHEMA'),('AUTH_FAILED','AUTH_FAILED','CONFIGURATION')]:
            with self.subTest(status=status),patch('adapters.ai.transport.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(
                {'status':status,'failure_stage':stage,'retryable':status!='AUTH_FAILED','http_status':503,'raw_response':'SECRET','prompt':'SECRET'}))) as call:
                with self.assertRaises(AdvisoryProviderFailure) as caught:ProviderTransport(ROOT).analyze({'symbol':'bj920161','tracking_session_id':'test','input_id':'test','input_hash':'test','created_at':'2026-09-17T01:00:00+00:00'},'low',{},'TEST',{},advisory_diagnostics=True)
                meta=caught.exception.failure_metadata
                self.assertEqual(meta['error_code'],expected);self.assertEqual(meta['stage'],stage);self.assertNotIn('SECRET',str(meta));call.assert_called_once()

    def test_transport_http_status_and_retry_semantics_without_worker(self):
        from adapters.ai.transport import ProviderTransport
        from contracts.live.advisory import AdvisoryProviderFailure
        cases=((400,'MODEL_INVALID','MODEL_INVALID',False,'BadRequestError'),
               (401,'AUTH_FAILED','AUTH_FAILED',False,'AuthenticationError'),
               (403,'HTTP_ERROR','PROVIDER_HTTP_ERROR',False,'PermissionDeniedError'),
               (429,'RATE_LIMITED','PROVIDER_RATE_LIMITED',True,'RateLimitError'),
               (502,'HTTP_ERROR','PROVIDER_HTTP_ERROR',True,'InternalServerError'))
        for http,status,expected,retryable,kind in cases:
            with self.subTest(http=http),patch('adapters.ai.transport.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({
                'status':status,'failure_stage':'PROVIDER','http_status':http,'retryable':retryable,
                'provider_attempt_count':1,'transport_exception_type':kind,'raw_response':'SECRET'}))):
                with self.assertRaises(AdvisoryProviderFailure) as caught:
                    ProviderTransport(ROOT).analyze({'symbol':'bj920161','tracking_session_id':'test','input_id':'test','input_hash':'test','created_at':'2026-09-17T01:00:00+00:00'},'low',{},'TEST',{},advisory_diagnostics=True)
                meta=caught.exception.failure_metadata
                self.assertEqual((meta['error_code'],meta['http_status'],meta['retryable']),
                                 (expected,http,retryable))
                self.assertEqual(meta['provider_attempt_count'],1)
                self.assertEqual(meta['transport_exception_type'],kind)
                self.assertNotIn('SECRET',str(meta))

if __name__=='__main__':unittest.main()
