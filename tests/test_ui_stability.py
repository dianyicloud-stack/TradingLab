import unittest,time,copy,json
from threading import Event
from unittest.mock import Mock
from pathlib import Path
from app.system.service import SystemHealth
from app.system.module import create_module,HealthRouter
from app.live.observation import ObservationRouter
from bridges.market_agent import project
from contracts.system import HealthCheck

ROOT=Path(__file__).resolve().parents[1]
class UIStabilityTests(unittest.TestCase):
    def test_system_page_does_not_run_probe(self):
        probe=Mock(side_effect=AssertionError('expensive probe on GET'))
        health=SystemHealth([('expensive',probe)]);module=create_module(health)
        for _ in range(5):module.page();module.health();HealthRouter(health).route('GET','/api/system/summary')
        probe.assert_not_called();self.assertEqual(health.read()['overall'],'UNKNOWN')
    def test_explicit_diagnostics_nonblocking_coalesced_and_dated(self):
        entered=Event();release=Event();calls=[]
        def slow():calls.append(1);entered.set();release.wait(2);return HealthCheck('x','x','READY','ok')
        health=SystemHealth([('x',slow)]);health.diagnose();self.assertTrue(entered.wait(1))
        for _ in range(10):health.diagnose();self.assertEqual(health.read()['diagnostic_state'],'RUNNING')
        self.assertEqual(calls,[1]);release.set()
        for _ in range(100):
            if health.read()['diagnostic_state']=='COMPLETE':break
            time.sleep(.01)
        a=health.read();b=health.read();self.assertEqual(a['checked_at'],b['checked_at']);self.assertEqual(a['overall'],'READY')
    def test_failed_probe_does_not_become_ready(self):
        h=SystemHealth([('x',lambda:(_ for _ in ()).throw(ValueError()))]);h.snapshot();self.assertEqual(h.read()['overall'],'DEGRADED')
    def fixture(self):
        return {'source':'TEST','version':3,'fact_version':7,'agent_state':'RUNNING','last_cycle_at':'2026-09-16T16:13:33+08:00','sessions':[{'tracking_session_id':'s','symbol':'bj920161','date':'2026-09-16','rows':[{'unused':'duplicated'}],'selectedBoardCode':'NEW','selectedBoardName':'新板块'}],
            'facts':[{'kind':'OBSERVATION','identity':'s:1','revision':1,'sha256':'abc','recorded_at':'2026-09-16T08:13:33Z','payload':{'tracking_session_id':'s','raw':{'requestedTime':'16:13','stockDataTime':'15:00','intervalStart':'15:00','intervalEnd':'16:13','source':'now','capturedAt':'2026-09-16 16:13:33','price':21,'boardCode':'OLD','boardName':'旧板块','amountTrusted':False}}}], 'event_statuses':{},'analysis_state':{'do_not_show':'cursor'}}
    def test_late_fetch_preserves_native_interval_but_not_fake_market_time(self):
        value=self.fixture();before=copy.deepcopy(value);result=project(value)[0];row=result['observations'][0]
        self.assertEqual(row['timestamp'],'2026-09-16T15:00:00+08:00');self.assertEqual(row['requested_at'],'2026-09-16T16:13:00+08:00')
        self.assertEqual(row['available_at'],'2026-09-16T16:13:33+08:00');self.assertEqual(row['interval_end'],'2026-09-16T16:13:00+08:00');self.assertEqual(value,before)
    def test_historical_board_not_replaced_by_current_selection(self):
        row=project(self.fixture())[0]['observations'][0];self.assertEqual(row['board_id'],'OLD');self.assertEqual(row['board_name'],'旧板块');self.assertFalse(row['amount_trusted'])
    def test_unknown_board_stays_unknown(self):
        v=self.fixture();v['facts'][0]['payload']['raw'].pop('boardCode');v['facts'][0]['payload']['raw'].pop('boardName');self.assertIsNone(project(v)[0]['observations'][0]['board_id'])
    def test_scheduled_observation_preserves_interval_end(self):
        v=self.fixture();v['facts'][0]['payload']['raw'].update(source='auto',requestedTime='10:35',stockDataTime='10:34',intervalStart='10:30',intervalEnd='10:35')
        row=project(v)[0]['observations'][0];self.assertTrue(row['interval_complete']);self.assertIn('10:35',row['timestamp']);self.assertIn('10:34',row['market_observed_at'])
    def test_display_query_omits_duplicate_rows_without_modifying_owner(self):
        v=self.fixture();port=Mock(root=Path('test'));port.query.side_effect=lambda:copy.deepcopy(v);router=ObservationRouter(port)
        result=router.route('GET','/api/data-observation/state',{'view':'display'})[1]
        self.assertNotIn('rows',result['sessions'][0]);self.assertNotIn('analysis_state',result);self.assertIn('rows',v['sessions'][0]);self.assertEqual(result['facts'],v['facts'])
        unchanged=router.route('GET','/api/data-observation/state',{'view':'display','since':result['display_revision']})[1];self.assertTrue(unchanged['unchanged']);self.assertNotIn('facts',unchanged)
        port.command.assert_not_called();port.formal.assert_not_called()
    def test_revision_invalidates_display_on_command_or_fact_change(self):
        v=self.fixture();port=Mock(root=Path('test'));port.query.side_effect=lambda:copy.deepcopy(v);router=ObservationRouter(port)
        first=router.route('GET','/api/data-observation/state',{'view':'display'})[1]
        for field in ('version','fact_version'):
            v[field]+=1;new=router.route('GET','/api/data-observation/state',{'view':'display','since':first['display_revision']})[1];self.assertNotIn('unchanged',new)
    def test_first_round_prompt_separates_comparison_and_quality(self):
        from engines.live.advisory import PROMPT
        self.assertIn('不等于当前市场证据不足',PROMPT);self.assertIn('字段名和枚举保持原样',PROMPT)
    def test_observation_cached_get_does_not_wait_for_owner_or_lose_last_success(self):
        value=self.fixture();value['event_badges']={};value['read_model']={'collected_at':'2026-09-16T07:00:00Z','refresh_state':'REFRESH_FAILED','error':'owner offline'}
        port=Mock(root=Path('test'));port.query.side_effect=AssertionError('GET queried slow producer')
        router=ObservationRouter(port);router.read_model=Mock();router.read_model.read.return_value=value
        status,result,_=router.route('GET','/api/data-observation/state',{'view':'display'})
        self.assertEqual(status,200);self.assertTrue(result['facts']);self.assertEqual(result['read_model']['refresh_state'],'REFRESH_FAILED');port.query.assert_not_called()
    def test_observation_cached_wrong_generation_never_crosses_source(self):
        value=self.fixture();value['source_generation']='OLD';source=Mock();source.identity.return_value={'source_generation':'NEW','source_root':'different'}
        router=ObservationRouter(Mock(),active_source=source);router.read_model=Mock();router.read_model.read.return_value=value
        status,result,_=router.route('GET','/api/data-observation/state',{'view':'display'})
        self.assertEqual(result['status'],'INITIAL_LOADING');self.assertNotIn('facts',result)

if __name__=='__main__':unittest.main()
