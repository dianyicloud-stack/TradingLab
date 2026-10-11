"""Isolated data/time/queue/read races. Browser tests use the actual exporter."""
from pathlib import Path
from datetime import timedelta
from threading import Thread,Event
from copy import deepcopy
import json,hashlib,tempfile,time,unittest
from tests.support.native import NativeFixture
from contracts.live.bridge import BridgeError
from engines.live.triggers import RULE
from engines.live.reading import event_summary
ROOT=Path(__file__).resolve().parents[1]

class ReadingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='reading-',dir=ROOT/'tests');self.addCleanup(self.tmp.cleanup)
  self.f=NativeFixture(Path(self.tmp.name));self.addCleanup(self.f.close);self.a=self.f.advisory
  self.a.market_is_open=lambda day:True
  self.f.now=self.f.now.replace(hour=9,minute=37,second=0)
  self.directory=self.f.workspace/'exports/trading_lab/v1';self.directory.mkdir(parents=True)
  self.rows=[];self.publish()
 def publish(self):
  self.f.bridge.snapshots=deepcopy(self.rows)
 def sample(self,price=10,symbol='bj920161',seconds=5,delivery='LIVE',publisher='page1'):
  self.f.now+=timedelta(seconds=seconds);m=self.f.members[symbol];at=self.f.now.isoformat();trade=self.f.now.replace(minute=35,second=0).isoformat()
  raw={'price':price,'vwap':9.9,'timestamp':at,'source_updated_at':at,'trade_source_captured_at':trade}
  encoded=json.dumps(raw,separators=(',',':'));sha=hashlib.sha256(encoded.encode()).hexdigest();sid=m['tracking_session_id']+':'+at+':'+trade
  row={'schema_version':'1','sample_id':sid,'record_id':sid+':'+sha[:16],'tracking_session_id':m['tracking_session_id'],
   'session_date':m['session_date'],'symbol':symbol,'publisher_id':publisher,'source_format':'V2A_RUNTIME_SNAPSHOT_V1',
   'delivery':delivery,'quality':'PRICE_AVAILABLE','market_observed_at':at,'sampled_at':at,'available_at':at,
   'raw_payload':raw,'raw_payload_json':encoded,'native_sha256':sha,'fields':{'price':price,'vwap':9.9},
   'field_times':{'price':{'as_of':at},'vwap':{'as_of':trade}},'source':'V2A_NATIVE'}
  self.rows.append(row);self.publish();return row
 def wait(self,predicate):
  for _ in range(200):
   if predicate():return
   time.sleep(.02)
  self.fail('timed out')
 def test_snapshot_without_handoff(self):
  r=self.sample();data=self.a.freeze('bj920161','MANUAL');self.assertIsNone(data['source_handoff_id']);self.assertEqual(data['live_observation']['record_id'],r['record_id'])
 def test_manual_0937_without_next_observation(self):
  r=self.sample();o=self.a.analyze('bj920161');self.assertEqual(o['data_through_at'],r['market_observed_at']);self.assertIsNone(o['structure_through_at'])
 def test_field_times_stay_distinct(self):
  self.sample();o=self.a.analyze('bj920161');times=o['source_field_times'][-1]['field_times'];self.assertIn('09:35',times['vwap']['as_of']);self.assertIn('09:37',times['price']['as_of'])
 def test_untimed_raw_cache_not_in_ai_evidence(self):
  self.sample();frozen=self.a.freeze('bj920161','MANUAL')
  for row in [frozen['current_state'],frozen['live_observation'],*frozen['context_evidence']['observations']]:
   self.assertNotIn('raw_payload',row);self.assertNotIn('raw_payload_json',row);self.assertTrue(row['native_sha256'])
  self.assertIn('raw_payload',self.rows[0])
 def test_full_manual_time_metadata(self):
  self.sample();o=self.a.analyze('bj920161')
  for key in ('requested_at','input_frozen_at','data_through_at','ai_started_at','ai_completed_at'):self.assertTrue(o[key]);self.assertRegex(o[key],r'(Z|[+-]\d\d:\d\d)$')
  self.assertIsNone(o['triggered_at']);self.assertIn('09:37',o['context_window']['start'])
 def test_quote_without_event_is_new_data(self):
  self.sample();self.a.analyze('bj920161');self.sample(10.1);self.assertTrue(self.a.analyze('bj920161')['advisory_id'])
 def test_no_new_then_explicit_reanalysis(self):
  self.sample();one=self.a.analyze('bj920161')
  with self.assertRaises(BridgeError) as e:self.a.analyze('bj920161')
  self.assertEqual(e.exception.code,'NO_NEW_ADVISORY_DATA');two=self.a.analyze('bj920161',force=True)
  self.assertEqual(two['trigger_type'],'MANUAL_REANALYSIS');self.assertGreater(two['request_sequence'],one['request_sequence'])
 def test_account_change_is_reevaluation(self):
  self.sample();self.a.portfolio_context=lambda s:{'position_quantity':0};self.a.analyze('bj920161');self.a.portfolio_context=lambda s:{'position_quantity':100}
  self.assertEqual(self.a.analyze('bj920161')['reevaluation_reason'],'ACCOUNT_CHANGED')
 def test_valuation_refresh_during_ai_is_not_an_account_operation(self):
  self.sample();context={'position_quantity':100,'total_equity':1000,'position':{'qty':100,'quote':{'timestamp':'09:37:05'}}}
  self.a.portfolio_context=lambda s:deepcopy(context);self.a.portfolio_result=lambda *args:{'status':'PORT_REACHED'}
  def refresh():context.update(total_equity=1010);context['position']['quote']['timestamp']='09:37:06'
  self.f.provider.callback=refresh;opinion=self.a.analyze('bj920161')
  self.assertEqual(self.a.runtime.portfolio_outcome(opinion['advisory_id'])['status'],'PORT_REACHED')
 def test_model_change_requires_explicit_reanalysis(self):
  self.sample();self.a.analyze('bj920161');self.a.save_settings({'reasoning_effort':'high'})
  with self.assertRaises(BridgeError) as e:self.a.analyze('bj920161')
  self.assertEqual(e.exception.code,'NO_NEW_ADVISORY_DATA')
  self.assertEqual(self.a.analyze('bj920161',force=True)['trigger_type'],'MANUAL_REANALYSIS')
 def test_future_field_rejected(self):
  self.sample();self.rows[-1]['field_times']['vwap']['as_of']=(self.f.now+timedelta(minutes=1)).isoformat();self.publish()
  with self.assertRaises(BridgeError) as e:self.a.freeze('bj920161','MANUAL')
  self.assertEqual(e.exception.code,'ADVISORY_FUTURE_DATA')
 def test_future_previous_completion_excluded_even_same_market_window(self):
  self.sample();at=self.f.now;self.f.now+=timedelta(seconds=10);self.a.analyze('bj920161');self.f.now=at
  frozen=self.a.freeze('bj920161','MANUAL');self.assertIsNone(frozen['previous_advisory']);self.assertFalse(frozen['previous_eligibility']['eligible'])
 def test_snapshot_enough_for_market_not_full_structure(self):
  self.sample();h=self.a.symbol_health('bj920161');self.assertEqual(h['market']['evidence_status'],'SNAPSHOT_WITHOUT_STRUCTURE');self.assertEqual(h['market']['status'],'FRESH')
 def test_event_price_not_current_quote(self):
  self.f.append(observation=False);c=self.a.stock_cards()[0];self.assertIsNone(c['session']['price'])
 def test_queue_preserves_request_window(self):
  entered,release=Event(),Event();original=self.f.provider.analyze
  def slow(*args):entered.set();release.wait(3);return original(*args)
  self.f.provider.analyze=slow;first=self.sample();results=[];thread=Thread(target=lambda:results.append(self.a.analyze('bj920161')));thread.start();self.assertTrue(entered.wait(2))
  second=self.sample(10.1);queued=self.a.analyze('bj920161');self.assertTrue(queued['queued']);self.sample(10.2)
  release.set();thread.join(4);self.wait(lambda:len(self.f.provider.calls)==2)
  self.assertEqual(self.f.provider.calls[0]['frozen']['data_through_at'],first['market_observed_at']);self.assertEqual(self.f.provider.calls[1]['frozen']['data_through_at'],second['market_observed_at'])
  self.assertEqual(self.a.runtime.portfolio_outcome(results[0]['advisory_id'])['reason'],'SUPERSEDED_ANALYSIS')
 def test_late_old_window_does_not_replace_new(self):
  self.sample();old=self.a.freeze('bj920161','MANUAL');self.sample(10.2);new=self.a.analyze('bj920161')
  late=self.a._perform(old,self.a.effective('bj920161'),'late-test')
  self.assertFalse(late['effective_result']);self.assertEqual(self.a.latest('bj920161')['advisory_id'],new['advisory_id']);self.assertEqual(self.a.runtime.portfolio_outcome(late['advisory_id'])['reason'],'SUPERSEDED_ANALYSIS')
 def test_model_switch_in_flight_preserves_last_success(self):
  self.sample();one=self.a.analyze('bj920161');self.sample(10.2);original=self.f.provider.analyze
  def changing(*args):self.a.save_settings({'reasoning_effort':'high'});return original(*args)
  self.f.provider.analyze=changing;two=self.a.analyze('bj920161');self.assertTrue(two['effective_result']);self.assertEqual(two['model'],one['model']);self.assertEqual(self.a.latest('bj920161')['advisory_id'],two['advisory_id'])
 def test_duplicate_queued_request_no_second_ai(self):
  entered,release=Event(),Event();original=self.f.provider.analyze
  def slow(*args):entered.set();release.wait(3);return original(*args)
  self.f.provider.analyze=slow;self.sample();thread=Thread(target=lambda:self.a.analyze('bj920161'));thread.start();self.assertTrue(entered.wait(2))
  queued=self.a.analyze('bj920161');release.set();thread.join(4)
  self.wait(lambda:self.a.runtime.coordinator(queued['tracking_session_id'])['state']=='IDLE')
  self.assertEqual(len(self.f.provider.calls),1)
 def test_old_confirmation_plan_rejected_without_account_write(self):
  self.sample();one=self.a.analyze('bj920161');self.sample(10.2);self.a.analyze('bj920161')
  opinion,frozen=self.a.execution_bundle(one['advisory_id']);self.assertFalse(opinion['effective_result'])
  self.assertTrue(self.a.by_id(one['advisory_id'])['effective_result'])
  self.assertEqual(self.f.p.on_advisory(opinion,frozen,True),{'status':'DEFERRED','reason':'SUPERSEDED_ANALYSIS'})
 def test_unread_major_change_not_small_decimal(self):
  self.sample();one=self.a.analyze('bj920161');sid=one['tracking_session_id'];self.a.mark_read('bj920161',{'tracking_session_id':sid,'advisory_id':one['advisory_id']})
  original=self.f.provider.analyze
  def changed(*args):
   value=original(*args);value['analysis']['action']='REDUCE';return value
  self.f.provider.analyze=changed;self.sample(10.2);self.a.analyze('bj920161');self.assertEqual(self.a.stock_cards()[0]['unread']['important_changes'],1)
  self.assertEqual(self.a._change_severity({'action':'WATCH','dominant_side':'SELLER','dominance_score':6.01},one),'INFO')
 def enable(self):
  self.a.preferences('bj920161',{'auto_event_types':[RULE],'auto_ai_mode':'ALL_EVENTS'});self.sample();self.a.ingest()
 def test_triggers_default_off(self):
  self.sample();self.a.ingest();self.sample(11);self.a.ingest();self.assertFalse(self.a.runtime.native_control(self.f.members['bj920161']['tracking_session_id'],'LIVE_TRIGGERS'))
 def test_selected_rule_real_sources_and_dedup(self):
  self.enable();self.sample(10.2);self.a.ingest();self.a.ingest();tr=self.a.freeze('bj920161','AUTO_EVENT')['live_triggers'];self.assertEqual(len(tr),1);self.assertEqual(tr[0]['source'],'LIVE_TRIGGER');self.assertTrue(tr[0]['evidence']['before_id'])
  self.a.poll_auto();self.f.now+=timedelta(seconds=4);self.a.poll_auto();self.assertEqual(len(self.f.provider.calls),1)
  o=self.a.latest('bj920161');self.assertTrue(o['triggered_at']);self.assertEqual(o['data_through_at'],self.rows[-1]['market_observed_at'])
 def test_first_backfill_reconnect_no_trigger(self):
  self.enable();self.sample(12,delivery='BACKFILL');self.a.ingest();self.sample(14,publisher='page2');self.a.ingest();self.sample(16,seconds=80);self.a.ingest()
  self.assertFalse(self.a.freeze('bj920161','MANUAL')['live_triggers'])
 def test_listener_reconnect_does_not_turn_backlog_into_trigger(self):
  self.enable()
  for _ in range(10):self.sample(11)
  self.a.ingest();self.assertFalse(self.a.freeze('bj920161','MANUAL')['live_triggers'])
  self.sample(12,delivery='RECOVERED');self.sample(13);self.a.ingest()
  self.assertFalse(self.a.freeze('bj920161','MANUAL')['live_triggers'])
 def test_native_and_live_coalesce(self):
  self.enable();self.sample(10.2);self.f.append(observation=False);self.publish();self.a.ingest();self.a.preferences('bj920161',{'auto_event_types':[RULE,'NEW_HIGH']});self.a.poll_auto();self.f.now+=timedelta(seconds=4);self.a.poll_auto()
  self.assertEqual(len(self.f.provider.calls),1);self.assertEqual({r['source'] for r in self.f.provider.calls[0]['frozen']['trigger_events']},{'V2A_NATIVE','LIVE_TRIGGER'})
 def test_read_position_exact_version(self):
  self.sample();one=self.a.analyze('bj920161');self.sample(10.2);two=self.a.analyze('bj920161');sid=self.f.members['bj920161']['tracking_session_id']
  self.a.mark_read('bj920161',{'tracking_session_id':sid,'advisory_id':one['advisory_id'],'event_seq':0})
  c=next(c for c in self.a.stock_cards() if c['session']['symbol']=='bj920161');self.assertEqual(c['unread']['opinions'],1)
  self.a.mark_read('bj920161',{'tracking_session_id':sid,'advisory_id':two['advisory_id'],'event_seq':0});self.assertEqual(self.a.stock_cards()[0]['unread']['opinions'],0)
 def test_poll_does_not_mark_read(self):
  self.sample();self.a.analyze('bj920161');self.a.stock_cards();self.a.stock_cards();self.assertEqual(self.a.stock_cards()[0]['unread']['opinions'],1)
 def test_wrong_session_read_refused(self):
  self.sample();one=self.a.analyze('bj920161')
  with self.assertRaises(BridgeError):self.a.mark_read('sh688696',{'tracking_session_id':self.f.members['sh688696']['tracking_session_id'],'advisory_id':one['advisory_id']})
 def test_fold_preference_no_business_side_effect(self):
  self.sample();self.a.analyze('bj920161');before=self.a.runtime.cursor(self.f.members['bj920161']['tracking_session_id']);count=len(self.f.provider.calls)
  self.a.preferences('bj920161',{'collapsed':True});self.assertTrue(self.a.effective('bj920161')['collapsed']);self.assertEqual(self.a.runtime.cursor(before['tracking_session_id']),before);self.assertEqual(len(self.f.provider.calls),count)
 def test_multi_symbol_independent_unread(self):
  for symbol in self.f.members:self.sample(symbol=symbol);self.a.analyze(symbol)
  sid=self.f.members['bj920161']['tracking_session_id'];self.a.mark_read('bj920161',{'tracking_session_id':sid,'advisory_id':self.a.latest('bj920161')['advisory_id']})
  values={c['session']['symbol']:c['unread']['opinions'] for c in self.a.stock_cards()};self.assertEqual(values,{'bj920161':0,'sh688696':1})
 def test_repeated_low_no_invented_trend(self):
  v=event_summary([{'timestamp':'09:35:00','label':'新低','price':20.5},{'timestamp':'09:37:00','label':'新低','price':20.67}],'2026-09-09')
  self.assertEqual(v['text'],'近15分钟出现2次“新低”类事件');self.assertNotIn('连续',v['text'])
 def test_failure_keeps_opinion_and_unread(self):
  self.sample();one=self.a.analyze('bj920161');self.sample(10.2)
  def fail(*args):raise RuntimeError('timeout')
  self.f.provider.analyze=fail
  with self.assertRaises(BridgeError):self.a.analyze('bj920161')
  self.assertEqual(self.a.latest('bj920161')['advisory_id'],one['advisory_id']);self.assertEqual(self.a.stock_cards()[0]['unread']['opinions'],1)

if __name__=='__main__':unittest.main()
