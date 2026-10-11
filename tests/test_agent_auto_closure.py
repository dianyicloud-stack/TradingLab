from pathlib import Path
from datetime import timedelta,timezone
from copy import deepcopy
import unittest,tempfile,time,json
from unittest.mock import patch
from threading import Event
from tests.agent_auto_fixture import AgentAutoFixture
from engines.live.qualification import NATIVE_EVENTS,validate,VERSION
from engines.live.synchronization import status
from bridges.market_agent import project

class AgentAutoClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='auto-owner-');self.addCleanup(self.tmp.cleanup)
        self.f=AgentAutoFixture(Path(self.tmp.name));self.addCleanup(self.f.close);self.a=self.f.advisory;self.symbol='bj920161'
    def eligibility(self):
        frozen=self.a.freeze(self.symbol,'AUTO_EVENT');return self.a.eligibility(frozen,self.a.effective(self.symbol))
    def test_actual_owner_auto_path_and_no_account_execution(self):
        self.f.advance_native();self.f.auto_cycle();o=self.a.latest(self.symbol)
        self.assertIsNotNone(o,self.f.app.live_loop.last_error);self.assertEqual(o['trigger_type'],'AUTO_EVENT')
        self.assertEqual(len(self.f.provider.calls),1)
        self.assertEqual(self.a.runtime.latest_request(o['tracking_session_id'])['payload']['task']['source'],'AUTO')
        frozen=self.a.opinions.input(o['input_id']);self.assertEqual(frozen['evidence_validation']['version'],VERSION)
        self.assertEqual(frozen['portfolio_context']['ai_execution_mode'],'ADVISORY_ONLY')
    def test_off_important_all_empty_override(self):
        self.f.advance_native();self.a.ingest()
        settings=self.a.effective(self.symbol);frozen=self.a.freeze(self.symbol,'AUTO_EVENT')
        self.assertTrue(self.a.eligibility(frozen,{**settings,'auto_ai_mode':'ALL_EVENTS'})['eligible'])
        self.assertFalse(self.a.eligibility(frozen,{**settings,'auto_ai_mode':'OFF'})['eligible'])
        self.assertFalse(self.a.eligibility(frozen,{**settings,'auto_ai_mode':'IMPORTANT_ONLY'})['eligible'])
        self.assertIn('EVENT_FILTER_EMPTY',self.a.eligibility(frozen,{**settings,'auto_event_types':[]})['blockers'])
    def test_full_catalog_before_types_occur_and_live_trigger_separate(self):
        card=self.a.stock_cards()[0];self.assertTrue(set(NATIVE_EVENTS)<=set(card['event_types']))
        self.a.preferences(self.symbol,{'auto_event_types':list(NATIVE_EVENTS)})
        self.assertNotIn('LIVE_PRICE_MOVE_60S',self.a.effective(self.symbol)['auto_event_types'])
        self.assertIn('LOW_VOLUME_PULLBACK',self.a.effective(self.symbol)['auto_event_types'])
        self.a.preferences(self.symbol,{'auto_event_types':[]});self.assertEqual(self.a.effective(self.symbol)['auto_event_types'],[])
        self.a.preferences(self.symbol,{'auto_event_types':None});self.assertEqual(self.a.effective(self.symbol).get('auto_event_types'),['NEW_HIGH'])
    def test_optional_missing_allowed_core_missing_explained(self):
        self.f.advance_native();frozen=self.a.freeze(self.symbol,'AUTO_EVENT');self.assertTrue(any(e['status']=='SUFFICIENT' for e in frozen['evidence_validation']['events']))
        facts=self.bridge_facts();event=next(e for e in reversed(facts['events']) if e['type']=='NEW_HIGH')
        broken=deepcopy(facts['observations'])
        for row in broken:
            if row.get('native_rule_evidence'):row['native_rule_evidence']['high']=None
        q=validate(event,broken,facts['session']);self.assertEqual(q['status'],'INSUFFICIENT');self.assertIn('high',q['missing'])
    def bridge_facts(self):return self.f.bridge.advisory_facts(self.symbol)
    def test_quality_version_and_zero_false_are_not_missing(self):
        self.f.advance_native();facts=self.bridge_facts();event=next(e for e in reversed(facts['events']) if e['type']=='NEW_HIGH');rows=deepcopy(facts['observations'])
        formal=[r for r in rows if r.get('native_rule_evidence') and r['native_rule_evidence']['requestedTime']==event['requested_time']];formal[-1]['native_rule_evidence']['high']=0
        q=validate(event,rows,facts['session']);self.assertNotIn('high',q['missing'])
        formal[-1]['quality_version']='future-99';q=validate(event,rows,facts['session']);self.assertIn('QUALITY_VERSION_UNSUPPORTED',q['missing'])
    def test_delayed_evidence_reevaluates_after_scan_without_advancing_success(self):
        self.f.advance_native();query=self.f.port.query;view=query()
        incomplete=deepcopy(view)
        for r in incomplete['facts']:
            if r['kind']=='OBSERVATION' and r['payload']['symbol']==self.symbol:r['payload']['raw']['high']=None
        with patch.object(self.f.port,'query',return_value=incomplete):
            self.a.ingest();q=self.eligibility();self.assertIn('EVENT_EVIDENCE_INSUFFICIENT',q['blockers']);self.a.poll_auto()
        self.assertFalse(self.f.provider.calls);self.f.auto_cycle();self.assertIsNotNone(self.a.latest(self.symbol))
    def test_setting_boundary_never_replays_old_event_or_changes_success_cursor(self):
        self.f.advance_native();sid=self.bridge_facts()['session']['tracking_session_id'];self.a.preferences(self.symbol,{'auto_event_types':list(NATIVE_EVENTS)})
        self.f.auto_cycle();self.assertFalse(self.f.provider.calls);self.assertIsNone(self.a.runtime.cursor(sid))
        self.f.advance_native();self.f.auto_cycle();self.assertEqual(len(self.a.history(self.symbol)),1)
    def test_failed_event_not_retried_on_each_snapshot(self):
        self.f.advance_native();self.a.ingest();self.a.poll_auto();self.f.now+=timedelta(seconds=4)
        with patch.object(self.f.provider,'analyze',side_effect=TimeoutError()):self.f.app.live_loop.poll()
        self.assertIn('FAILED_WINDOW',self.eligibility()['blockers'])
        self.f.now+=timedelta(seconds=5);self.f.sample();self.f.auto_cycle();self.assertFalse(self.f.provider.calls)
    def test_background_without_browser_and_two_symbols(self):
        self.f.prices['sh688601']+=2;self.f.advance_native();self.f.now+=timedelta(seconds=4)
        self.f.app.live_loop.start()
        end=time.monotonic()+8
        while time.monotonic()<end and len(self.f.provider.calls)<2:
            self.f.now+=timedelta(seconds=1);time.sleep(.15)
        self.assertEqual(len(self.f.provider.calls),2,self.f.app.live_loop.last_error)
    def test_sync_version_and_no_new_facts_does_not_age(self):
        self.a.ingest();f=self.bridge_facts();applied=self.a.runtime.ingestion(f['session']['tracking_session_id'])
        self.assertEqual(status(f['session'],applied,self.f.now+timedelta(hours=1))['status'],'SYNCED')
        self.f.advance_native();session=self.bridge_facts()['session']
        self.assertEqual(status(session,applied,self.f.now)['status'],'PENDING')
        self.assertEqual(status(session,applied,self.f.now+timedelta(seconds=16))['status'],'LAGGING')
        self.assertEqual(status(session,applied,self.f.now-timedelta(seconds=1))['status'],'CLOCK_SKEW')
        self.a.ingest();self.assertEqual(status(session,self.a.runtime.ingestion(session['tracking_session_id']),self.f.now)['status'],'SYNCED')
    def test_sync_identity_and_utc_equivalent(self):
        self.a.ingest();f=self.bridge_facts();applied=self.a.runtime.ingestion(f['session']['tracking_session_id'])
        self.assertEqual(status(f['session'],applied,self.f.now.astimezone(timezone.utc))['status'],'SYNCED')
        applied['source_watermark']['identity']='another-generation';self.assertEqual(status(f['session'],applied,self.f.now)['status'],'SOURCE_IDENTITY_MISMATCH')

    def test_sync_error_and_unknown_watermark_never_show_synced(self):
        self.a.ingest();facts=self.bridge_facts();applied=self.a.runtime.ingestion(facts['session']['tracking_session_id'])
        self.assertEqual(status(facts['session'],{**applied,'errors':[{'code':'SOURCE_EVENT_GAP'}]},self.f.now)['status'],'SOURCE_ERROR')
        self.assertEqual(status({**facts['session'],'source_watermark':None},applied,self.f.now)['status'],'UNKNOWN')
        self.f.advance_native();session=self.bridge_facts()['session']
        for row in session['source_commits']:row['at']='2026-09-18T09:40:00'
        value=status(session,applied,self.f.now);self.assertIsNone(value['lag_seconds']);self.assertEqual(value['reason'],'COMMIT_TIME_UNKNOWN')

    def test_ingest_error_does_not_advance_applied_watermark(self):
        self.a.ingest();facts=self.bridge_facts();sid=facts['session']['tracking_session_id'];before=self.a.runtime.ingestion(sid)['source_watermark']
        self.f.advance_native();facts=self.bridge_facts();facts['session']['source_errors']=[{'code':'SOURCE_EVENT_GAP'}]
        value=self.a.runtime.ingest(facts,self.a._stamp());self.assertEqual(value['source_watermark'],before)

    def test_actual_1015_low_volume_evidence_and_explicit_scope(self):
        value=json.loads((Path(__file__).parent/'fixtures/agent_low_volume_20260918.json').read_text(encoding='utf-8'))
        facts=project(value)[0];event=next(e for e in facts['events'] if e['event_id']=='E-TS-20260918-sz300474-01-0008')
        original=deepcopy(event);q=validate(event,facts['observations'],facts['session'])
        self.assertEqual(q['status'],'SUFFICIENT');self.assertEqual(event,original);self.assertEqual(event['severity'],'INFO')
        rows=deepcopy(facts['observations'])
        for row in rows:
            row['native_rule_evidence']['boardMedianChange']=None
            row['native_rule_evidence']['boardPending']=False
        self.assertEqual(validate(event,rows,facts['session'])['status'],'SUFFICIENT')
        for row in rows:row['native_rule_evidence']['volumeRatioSample']=0
        self.assertIn('VOLUME_COMPARISON_MISSING',validate(event,rows,facts['session'])['missing'])

    def test_volume_rule_needs_actual_comparator_not_every_old_volume(self):
        value=json.loads((Path(__file__).parent/'fixtures/agent_low_volume_20260918.json').read_text(encoding='utf-8'))
        facts=project(value)[0];event=next(e for e in facts['events'] if e['event_id']=='E-TS-20260918-sz300474-01-0008')
        rows=deepcopy(facts['observations']);associated=next(r for r in reversed(rows) if r['native_rule_evidence']['requestedTime']=='10:15')
        comparison=associated['native_rule_evidence']['comparisonTime']
        for r in rows:
            if r['native_rule_evidence']['requestedTime'] not in ('10:15',comparison):r['native_rule_evidence']['cumulativeVolume']=None
        self.assertEqual(validate(event,rows,facts['session'])['status'],'SUFFICIENT')
        for r in rows:
            if r['native_rule_evidence']['requestedTime']==comparison:r['native_rule_evidence']['cumulativeVolume']=None
        self.assertIn('comparison.cumulativeVolume',validate(event,rows,facts['session'])['missing'])

    def test_global_scope_and_mode_roundtrip_and_stock_override(self):
        self.a.preferences(self.symbol,{'auto_event_types':[]})
        self.a.save_settings({'auto_ai_mode':'IMPORTANT_ONLY','auto_event_types':list(NATIVE_EVENTS)})
        self.assertEqual(self.a.effective(self.symbol)['auto_event_types'],[])
        self.a.save_settings({'symbol':self.symbol,'auto_ai_mode':'OFF'})
        self.assertEqual(self.a.effective(self.symbol)['auto_ai_mode'],'OFF')
        self.a.save_settings({'symbol':self.symbol,'auto_ai_mode':None})
        self.assertEqual(self.a.effective(self.symbol)['auto_ai_mode'],'IMPORTANT_ONLY')
        self.assertEqual(self.a.effective(self.symbol)['configuration_origin']['mode'],'GLOBAL')

    def test_owner_live_trigger_is_independent_of_old_native_backlog(self):
        self.a.preferences(self.symbol,{'auto_event_types':['LIVE_PRICE_MOVE_60S'],'auto_ai_mode':'ALL_EVENTS'})
        self.a.ingest();self.f.now+=timedelta(seconds=5);self.f.prices[self.symbol]+=1;self.f.sample();self.a.ingest()
        self.assertEqual(self.eligibility()['eligible_trigger_count'],1,self.eligibility())
        self.f.auto_cycle();opinion=self.a.latest(self.symbol)
        self.assertIsNotNone(opinion);self.assertEqual(opinion['trigger_type'],'AUTO_EVENT');self.assertEqual(len(self.f.provider.calls),1)

    def test_owner_scheduler_manual_same_window_coalesces(self):
        entered,release=Event(),Event();original=self.f.provider.analyze
        def slow(*args):
            entered.set();release.wait(5);return original(*args)
        self.f.advance_native();self.a.ingest();self.a.poll_auto(wait=False);self.f.now+=timedelta(seconds=4)
        with patch.object(self.f.provider,'analyze',side_effect=slow):
            try:
                self.a.poll_auto(wait=False);self.assertTrue(entered.wait(3))
                manual=self.a.analyze(self.symbol);self.assertTrue(manual['coalesced'])
            finally:release.set()
            self.a._auto_futures[self.symbol].result(8)
        self.assertEqual(len(self.f.provider.calls),1);self.assertEqual(self.a.latest(self.symbol)['trigger_type'],'AUTO_EVENT')

    def test_owner_restart_does_not_replay_successful_window(self):
        from engines.live.advisory import AdvisoryService
        from engines.live.market_agent.service import AgentService
        self.f.advance_native();self.f.auto_cycle();old=self.a.latest(self.symbol);sid=old['tracking_session_id']
        cursor=self.a.runtime.cursor(sid);self.f.agent.close()
        self.f.agent=AgentService(self.f.agent.root,clock=lambda:self.f.now,calendar=lambda _:True)
        self.f.agent.repo.clock=lambda:self.f.now;self.f.port.service=self.f.agent
        restarted=AdvisoryService(self.f.bridge,self.a.runtime,self.a.opinions,self.f.provider,source='TEST',clock=lambda:self.f.now)
        restarted.market_is_open=lambda _:True;restarted.portfolio_context=self.a.portfolio_context
        try:
            restarted.ingest();restarted.poll_auto();self.f.now+=timedelta(seconds=4);restarted.poll_auto()
            self.assertEqual(len(self.f.provider.calls),1);self.assertEqual(restarted.runtime.cursor(sid),cursor)
            self.assertEqual(restarted.latest(self.symbol)['advisory_id'],old['advisory_id'])
        finally:restarted._auto_pool.shutdown(wait=True)

    def test_owner_next_day_has_new_boundary_and_no_previous_opinion(self):
        self.f.advance_native();self.f.auto_cycle();old=self.a.latest(self.symbol)
        self.f.now=(self.f.now+timedelta(days=3)).replace(hour=9,minute=35,second=40);self.f.bars={};self.f.sample()
        # TEST has no market network. Supply the new day's metadata through
        # the owner command, just as ADD seeded day one; do not forge facts.
        for symbol in self.f.prices:
            self.f.agent.command({'schema_version':'1.0','source':'TEST','action':'BOARD','command_id':'next-day-board-'+symbol,
                'expected_version':self.f.agent.query()['version'],'symbol':symbol,'name':'TEST '+symbol,'board':{'code':'BKTEST','name':'TEST'}})
        self.f.sample()
        self.a.ingest();self.a.poll_auto();facts=self.bridge_facts();sid=facts['session']['tracking_session_id']
        self.assertNotEqual(sid,old['tracking_session_id']);self.assertIsNone(self.a.runtime.cursor(sid))
        self.assertIsNone(self.a.freeze(self.symbol,'AUTO_EVENT')['previous_advisory']);self.assertEqual(len(self.f.provider.calls),1)
        self.f.advance_native();self.f.auto_cycle();new=self.a.latest(self.symbol)
        self.assertIsNotNone(new,{'eligibility':self.eligibility(),'listener_error':self.f.app.live_loop.last_error})
        self.assertEqual(new['tracking_session_id'],sid);self.assertEqual(len(self.f.provider.calls),2)

if __name__=='__main__':unittest.main()
