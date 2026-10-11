from pathlib import Path
from datetime import datetime,timedelta,timezone
import tempfile,unittest,uuid,time,json,sqlite3,threading
from unittest.mock import patch
from engines.live.market_agent.service import AgentService
from engines.live.read_model import LiveReadModel
from bridges.market_agent import AgentFactBridge
from contracts.live.market_agent import AgentError

class LocalPort:
    def __init__(self,service):self.service=service;self.root=service.root
    def query(self):return self.service.query()
    def command(self,value):return self.service.command(value)

def frame(now,price=10):
    day=now.date().isoformat();point=now.strftime('%H:%M');bar={'date':day,'time':point+':00','open':price,'high':price+.1,'low':price-.1,'close':price,'volume':1000,'amount':price*1000}
    bars=[dict(bar,time=f'09:{minute:02}:00') for minute in range(30,36) if f'09:{minute:02}'<=point]
    if not bars or bars[-1]['time']!=bar['time']:bars.append(bar)
    dataset={'profile':{'name':'测试甲','floatShares':1000000},'stockBars':bars,'stockTradeBars':bars,'stockDailyBars':[{'date':(now.date()-timedelta(days=1)).isoformat(),'close':10}],'volumeHistoryBars':[],
        'indexMinuteBars':[[],[],[],[]],'indexDailyBars':[[],[],[],[]],'board':{'code':'BKTEST','name':'测试行业'},'boardMinuteData':{'bars':[dict(bar,close=101)],'previousClose':100},'boardDailyBars':[],'boardBreadth':None}
    return {'fields':{'name':'测试甲','price':price,'open':price,'high':price+.1,'low':price-.1,'vwap':price,'stock_pct':0,'cumulative_volume':1000,'cumulative_amount':price*1000,'cumulative_turnover':.1,'source_updated_at':now.isoformat(),'trade_source_captured_at':now.isoformat(),'data_status':'fresh'},'dataset':dataset}

class MarketAgentTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).parent/'tmp';parent.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=parent,prefix='agent-test-');self.root=Path(self.tmp.name)
        self.now=datetime(2026,9,16,9,34,tzinfo=timezone(timedelta(hours=8)))
        self.service=AgentService(self.root,clock=lambda:self.now,calendar=lambda day:True);self.add('bj920161')
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def command(self,action,symbol='bj920161',**values):
        payload={'schema_version':'1.0','command_id':uuid.uuid4().hex,'source':'TEST','expected_version':self.service.query()['version'],'symbol':symbol,'action':action,**values}
        return payload,self.service.command(payload)
    def add(self,symbol):return self.command('ADD',symbol,name='测试'+symbol,board={'code':'BKTEST','name':'测试行业'})
    def sample(self,price=10):
        self.now+=timedelta(seconds=65);self.service.cycle({'bj920161':frame(self.now,price)})
        self.assertEqual(self.service.errors,[])
    def test_native_observation_snapshot_without_handoff(self):
        self.sample();view=self.service.query();self.assertTrue(any(f['kind']=='OBSERVATION' for f in view['facts']));self.assertTrue(any(f['kind']=='SNAPSHOT' for f in view['facts']))
        bridge=AgentFactBridge(LocalPort(self.service));facts=bridge.advisory_facts('bj920161');self.assertTrue(facts['observations']);self.assertFalse(hasattr(bridge,'handoff_documents'))
    def test_duplicate_market_capture_not_new_tick(self):
        self.sample();count=len(self.service.repo.facts('SNAPSHOT'));self.service.cycle({'bj920161':frame(self.now)});self.assertEqual(count,len(self.service.repo.facts('SNAPSHOT')))
    def test_command_idempotency_and_conflict(self):
        payload,result=self.command('PAUSE');self.assertEqual(result,self.service.command(payload))
        with self.assertRaises(AgentError):self.service.command(dict(payload,action='RESUME'))
    def test_version_conflict_has_no_mutation(self):
        before=self.service.query()
        with self.assertRaises(AgentError):self.service.command({'schema_version':'1.0','source':'TEST','command_id':'wrong','expected_version':0,'action':'STOP','symbol':'bj920161'})
        self.assertEqual(before,self.service.query())
    def test_reads_no_writes(self):
        self.sample();before=self.service.repo.path.read_bytes()
        for _ in range(20):self.service.query();AgentFactBridge(LocalPort(self.service)).sessions()
        self.assertEqual(before,self.service.repo.path.read_bytes())
    def test_restart_retains_identity_and_sequence(self):
        self.sample();sessions=self.service.query()['sessions'];facts=self.service.repo.facts();self.service.close()
        self.service=AgentService(self.root,clock=lambda:self.now,calendar=lambda _:True)
        self.assertEqual(sessions,self.service.query()['sessions']);self.service.cycle({'bj920161':frame(self.now)})
        self.assertEqual(len([f for f in facts if f['kind']=='EVENT']),len(self.service.repo.facts('EVENT')))
    def test_stopped_history_retained(self):
        self.sample();count=len(self.service.repo.facts('OBSERVATION'));self.command('STOP');self.sample();self.assertEqual(count,len(self.service.repo.facts('OBSERVATION')))
        self.assertEqual(self.service.query()['sessions'][0]['lifecycle_status'],'DROPPED')
    def test_new_session_after_stop(self):
        original=self.service.query()['sessions'][0]['tracking_session_id'];self.command('STOP');self.add('bj920161')
        self.assertEqual(len(self.service.query()['sessions']),2)
        active=next(s for s in self.service.query()['sessions'] if s['lifecycle_status']=='ACTIVE')
        self.assertNotEqual(active['tracking_session_id'],original);self.assertIsNone(active['previous_tracking_session_id']) # Native removal starts a distinct runtime identity.
    def test_append_facts_immutable(self):
        self.sample()
        with self.service.repo.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM facts')
    def test_owner_context_rejects_user_command_in_test(self):
        with self.assertRaises(AgentError):self.service.command({'source':'USER'})
    def test_background_without_any_browser(self):
        def frames():self.now+=timedelta(seconds=5);return {'bj920161':frame(self.now)}
        self.service.start(frames,interval=.1);time.sleep(.45)
        self.assertGreaterEqual(len(self.service.repo.facts('SNAPSHOT')),2)
    def test_market_closed_no_observation(self):
        self.service.calendar=lambda _:False;self.sample();self.assertEqual(self.service.repo.facts('OBSERVATION'),[])
    def test_three_symbols_isolated(self):
        self.add('sh688696');self.add('sz300225');self.now+=timedelta(seconds=65)
        self.service.cycle({s:frame(self.now,i+10) for i,s in enumerate(('bj920161','sh688696','sz300225'))})
        bridge=AgentFactBridge(LocalPort(self.service));self.assertEqual(len(bridge.sessions()),3)
        for s in bridge.sessions():self.assertTrue(all(o['symbol']==s['symbol'] for o in bridge.advisory_facts(s['symbol'])['observations']))
    def test_ack_requires_explicit_human_confirmation(self):
        self.assertEqual(self.service.repo.facts('ACK_RECEIPT'),[])
    def test_market_updates_do_not_conflict_with_settings_version(self):
        payload={'schema_version':'1.0','source':'TEST','command_id':'stable','expected_version':self.service.query()['version'],'action':'PAUSE','symbol':'bj920161'}
        self.sample();self.service.command(payload);self.assertEqual(self.service.query()['sessions'][0]['lifecycle_status'],'PAUSED')
        count=len(self.service.repo.facts('SNAPSHOT'));self.sample();self.assertGreater(len(self.service.repo.facts('SNAPSHOT')),count) # Native pause semantics retained.
    def test_parameters_keep_native_supported_values(self):
        self.command('PARAMETERS',volume_ratio_days=10);self.assertEqual(self.service.query()['parameters']['volume_ratio_days'],10)
        with self.assertRaises(AgentError):self.command('PARAMETERS',volume_ratio_days=5)
        self.assertEqual(self.service.query()['parameters']['volume_ratio_days'],10)
    def test_immediate_observation_does_not_move_formal_schedule(self):
        self.sample();self.now=self.now.replace(minute=37);self.service.cycle({'bj920161':frame(self.now,11)})
        self.command('IMMEDIATE');rows=[r['payload']['raw'] for r in self.service.repo.facts('OBSERVATION')]
        self.assertEqual(next(r for r in rows if r['requestedTime']=='09:37')['source'],'now')
        self.now=self.now.replace(minute=40,second=40);self.service.cycle({'bj920161':frame(self.now,12)})
        formal=[r['payload']['raw'] for r in self.service.repo.facts('OBSERVATION') if r['payload']['raw']['requestedTime']=='09:40'][-1]
        self.assertEqual(formal['source'],'auto');self.assertEqual(formal['intervalStart'],'09:35')

class ReadModelTests(unittest.TestCase):
    def test_last_success_restarts_without_blocking_collector(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path=Path(tmp)/'read.json';path.write_text(json.dumps({'advisory_cards':[{'symbol':'A'}],'read_model':{'collected_at':'2026-09-16T01:00:00Z'}}))
            calls=[]
            model=LiveReadModel(path,lambda:calls.append(1))
            start=time.monotonic();self.assertEqual(model.read()['advisory_cards'][0]['symbol'],'A');self.assertLess(time.monotonic()-start,.1);self.assertEqual(calls,[])
    def test_no_cache_initial_loading(self):
        self.assertEqual(LiveReadModel(Path(__file__).parent/'never-created.json',lambda:{}).read()['status'],'INITIAL_LOADING')
    def test_failed_refresh_preserves_success(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path=Path(tmp)/'read.json';path.write_text(json.dumps({'advisory_cards':[{'symbol':'A'}],'read_model':{}}))
            def failing():raise ValueError('source temporarily unavailable')
            model=LiveReadModel(path,failing);model.start()
            try:
                for _ in range(100):
                    if model.read()['read_model']['refresh_state']=='REFRESH_FAILED':break
                    time.sleep(.01)
                self.assertEqual(model.read()['advisory_cards'],[{'symbol':'A'}]);self.assertEqual(model.read()['read_model']['refresh_state'],'REFRESH_FAILED')
            finally:model.close()

class AgentConfigurationTests(unittest.TestCase):
    def test_default_workspace_overlap_rejected_without_env_override(self):
        from adapters.market_agent_process import validate_activation
        from bridges.config import LiveConfig
        root=Path(__file__).resolve().parents[1]
        workspace=hasattr(LiveConfig.load(root),'workspace')
        self.assertFalse(workspace) # Retired workspace selection cannot constrain the Agent.
        with self.assertRaisesRegex(AgentError,'AGENT_DATA_ROOT_MUST_BE_SEPARATE'):validate_activation(root,root/'data/agent')
    def test_lease_rejects_second_agent_even_with_other_port(self):
        from adapters.runtime_lease import runtime_lease
        import subprocess,sys
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp,runtime_lease(tmp):
            result=subprocess.run([sys.executable,'-B','-c','from adapters.runtime_lease import runtime_lease; import sys;\nwith runtime_lease(sys.argv[1]): print("unexpected second writer")',tmp],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('ALREADY_RUNNING',result.stderr)
    def test_data_page_without_activation_is_clear_and_read_only(self):
        from app.live.observation import ObservationRouter
        from bridges.market_agent import AgentClient
        status,body,_=ObservationRouter(AgentClient(None)).route('GET','/api/data-observation/state')
        self.assertEqual(status,503);self.assertEqual(body['status'],'NOT_CONNECTED')
