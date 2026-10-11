from pathlib import Path
import json,os,subprocess,sys,tempfile,time,unittest,urllib.request
from unittest.mock import patch
from datetime import datetime
from app.system.runtime_state import RuntimeState,atomic,read_json
from app.system.runtime_control import Recovery,Supervisor
from adapters.runtime_platform import identity,alive,force_owned
from engines.live.native_health import health
from engines.account.rules import TradingCalendar
ROOT=Path(__file__).resolve().parents[1]

def wait_for(function,seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=function()
        if value:return value
        time.sleep(.1)
    raise AssertionError('Timed out')

class RuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='runtime16-');self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
    def test_intent_migration_cas_idempotence_and_restart(self):
        s=RuntimeState(self.root);self.assertEqual(s.read()['listener'],'DISABLED')
        one=s.update({'listener':'ENABLED'});self.assertEqual(s.update({'listener':'ENABLED'}),one)
        s.update({'listener':'DISABLED'},one['revision'])
        with self.assertRaisesRegex(ValueError,'VERSION'):s.update({'listener':'ENABLED'},one['revision'])
        self.assertEqual(RuntimeState(self.root).read()['listener'],'DISABLED')
    def test_backoff_bounded_monotonic_manual_reset(self):
        now=[0];r=Recovery(lambda:now[0])
        for i in range(5):r.failed();now[0]+=61
        self.assertFalse(r.allowed());r.reset();self.assertTrue(r.allowed())
        r.failed();self.assertFalse(r.allowed());now[0]+=6;self.assertTrue(r.allowed())
    def test_windows_identity_creation_and_pid_reuse(self):
        record=identity();self.assertTrue(alive(record));self.assertFalse(alive({**record,'created':'1'}))
        with self.assertRaisesRegex(RuntimeError,'SCOPE'):force_owned(record,ROOT,self.root,'web')
    def test_calendar_rest_and_unknown(self):
        c=TradingCalendar()
        for at,phase in [('2026-09-18T09:20:00+08:00','BEFORE_OPEN'),('2026-09-18T12:00:00+08:00','LUNCH_BREAK'),('2026-09-25T10:00:00+08:00','NON_TRADING_DAY'),('2027-09-25T10:00:00+08:00','CALENDAR_UNKNOWN')]:
            self.assertEqual(health({},datetime.fromisoformat(at),c.is_open)['market_phase'],phase)
    def test_allowlist_latest_stop_wins_and_no_restart_stopped(self):
        s=Supervisor(ROOT,self.root);s.state.update({'web':'RUNNING'})
        old=s.submit({'action':'restart','target':'web'})['operation'];s.submit({'action':'stop','target':'web'})
        with patch.object(s,'_stop') as stop,patch.object(s,'_start') as start:s.execute(old)
        stop.assert_called_once();start.assert_not_called()
        with self.assertRaises(ValueError):s.submit({'action':'start','target':'arbitrary'})
    def test_no_process_restart_for_alive_or_long_ai(self):
        s=Supervisor(ROOT,self.root);s.state.update({'web':'RUNNING','agent':'RUNNING'})
        with patch.object(s,'inspect',return_value={'actual':'RUNNING','runtime':{'task_duration':230}}),patch.object(s,'_start') as start:s.tick()
        start.assert_not_called()
    def test_control_identity_does_not_adopt_old_descriptor(self):
        atomic(self.root/'runtime/web-instance.json',{'pid':os.getpid(),'url':'http://127.0.0.1:1'})
        self.assertEqual(Supervisor(ROOT,self.root).descriptor('web'),{})
    def test_real_isolated_process_graceful_force_and_adoption(self):
        project=self.root/'project';project.mkdir();data=self.root/'data';agent=self.root/'agent';agent.mkdir()
        for name in ('app/system/runtime_control.py','app/system/runtime_state.py','app/system/runtime_web.py','adapters/runtime_platform.py','engines/live/loop.py'):
            path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# isolated build marker')
        program=r'''from pathlib import Path
import sys,os,json,uuid,threading
sys.path.insert(0,ROOT)
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from app.system.runtime_state import atomic
from adapters.runtime_platform import identity
from adapters.runtime_lease import runtime_lease
service='agent' if Path(__file__).name=='market_data_agent.py' else 'web'
root=Path(sys.argv[sys.argv.index('--data-root')+1]) if service=='agent' else Path(os.environ['TRADING_LAB_DATA_ROOT'])
instance=uuid.uuid4().hex
class H(BaseHTTPRequestHandler):
 def send(self,value):
  b=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):self.send({'instance_id':instance,'status':'UP'})
 def do_POST(self):
  self.send({'status':'STOPPING'})
  if not (root/'hang').exists():threading.Thread(target=self.server.shutdown,daemon=True).start()
 def log_message(self,*args):pass
with runtime_lease(root):
 server=ThreadingHTTPServer(('127.0.0.1',0),H)
 atomic(root/('connection.json' if service=='agent' else 'runtime/web-instance.json'),{**identity(),'project':str(Path(__file__).parent),'data_root':str(root),'instance_id':instance,'url':f'http://127.0.0.1:{server.server_port}','token':'TEST'})
 server.serve_forever();server.server_close()
'''.replace('sys.path.insert(0,ROOT)','sys.path.insert(0,'+repr(str(ROOT))+')')
        for file in ('trading_lab.py','market_data_agent.py'):(project/file).write_text(program)
        atomic(agent/'activation.json',{'schema_version':'1.0','source':'USER','collection_enabled':True,'approved_at':'TEST'})
        s=Supervisor(project,data,0);s.agent_root=agent;s.state.update({'web':'RUNNING','agent':'RUNNING'})
        def cleanup():
            for name in ('web','agent'):
                if alive(s.descriptor(name)):s._stop(name,True)
        self.addCleanup(cleanup)
        s._start('agent');s._start('web');before=s.descriptor('web')
        fresh=Supervisor(project,data,0);fresh.agent_root=agent
        with patch.object(fresh,'_start') as start:fresh.tick()
        start.assert_not_called();s.submit({'action':'restart','target':'web'});s.execute(s.queue.get())
        self.assertNotEqual(before['instance_id'],s.descriptor('web')['instance_id']);self.assertFalse(alive(before))
        self.assertTrue(json.loads((agent/'activation.json').read_text())['collection_enabled'])
        (data/'hang').write_text('test')
        s.submit({'action':'force-stop','target':'web'});s.execute(s.queue.get())
        self.assertEqual(s.operations[-1]['status'],'COMPLETED',s.operations[-1]);self.assertFalse(alive(s.descriptor('web')))
        s.tick();self.assertFalse(alive(s.descriptor('web')))
        (data/'hang').unlink();s._stop('agent');self.assertFalse(alive(s.descriptor('agent')))
        for process in s.processes.values():process.wait(5)

    def test_independent_supervisor_restart_and_cli_with_no_web(self):
        from app.system.runtime_control import control_request,request,read
        env=dict(os.environ);env['TRADING_LAB_MARKET_AGENT_ROOT']=str(self.root/'agent')
        command=[sys.executable,'-B','-c','from app.system.runtime_control import serve; serve('+repr(str(ROOT))+','+repr(str(self.root))+',0)']
        def launch():
            p=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def ready():
                try:return control_request(self.root,{'action':'status'})
                except (OSError,ValueError):return None
            d=wait_for(ready);return p,d
        def close(p):
            if p.poll() is None:request(read(self.root/'runtime/supervisor.json'),'/shutdown-supervisor',{'confirm':'RELOAD_SUPERVISOR'});p.wait(10)
            error=p.stderr.read().decode('utf-8','replace');p.stderr.close();self.assertEqual(p.returncode,0,error)
        p,first=launch()
        try:
            value=control_request(self.root,{'action':'stop','target':'web'})
            self.assertEqual(value['desired']['web'],'STOPPED')
            wait_for(lambda:control_request(self.root,{'action':'status'})['operations'][-1]['status']=='COMPLETED')
        finally:close(p)
        p,second=launch()
        try:
            self.assertNotEqual(first['instance_id'],second['instance_id']);self.assertEqual(second['desired']['web'],'STOPPED')
        finally:close(p)

    def test_unrelated_port_and_process_are_not_owned(self):
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            s=Supervisor(ROOT,self.root,listener.getsockname()[1])
            with self.assertRaisesRegex(ValueError,'UNVERIFIED'):s._start('web')
        current={**identity(),'project':str(ROOT),'data_root':str(self.root),'instance_id':'not-a-service'}
        with self.assertRaisesRegex(RuntimeError,'IDENTITY'):force_owned(current,ROOT,self.root,'web')
        self.assertTrue(alive(current))
    def test_partial_stock_error_does_not_stop_other_stock(self):
        from tests.agent_auto_fixture import AgentAutoFixture
        from contracts.live.bridge import BridgeError
        f=AgentAutoFixture(self.root);self.addCleanup(f.close)
        original=f.bridge.advisory_facts;f.advance_native('sh688601')
        def facts(symbol):
            if symbol=='bj920161':raise BridgeError('TEST_SYMBOL_SOURCE_FAILURE')
            return original(symbol)
        with patch.object(f.bridge,'advisory_facts',side_effect=facts):
            f.auto_cycle()
            self.assertIsNotNone(f.advisory.latest('sh688601'))
            self.assertIn('bj920161',f.advisory.source_errors)
        self.assertEqual(len(f.provider.calls),1)
    def test_long_ai_drain_preserves_listener_intent_and_boundary(self):
        from tests.agent_auto_fixture import AgentAutoFixture
        from threading import Event
        from datetime import timedelta
        f=AgentAutoFixture(self.root);self.addCleanup(f.close)
        begin,release=Event(),Event();original=f.provider.analyze
        def analyze(*args,**kwargs):
            begin.set();release.wait(8);return original(*args,**kwargs)
        f.advance_native();f.app.live_loop.poll(wait_ai=False);f.now+=timedelta(seconds=4)
        with patch.object(f.provider,'analyze',side_effect=analyze):
            f.app.live_loop.start();self.assertTrue(begin.wait(3))
            wanted=f.app.runtime.state.read();sid=f.bridge.advisory_facts('bj920161')['session']['tracking_session_id']
            boundary=f.advisory.runtime.native_control(sid,'AUTO_POLICY_BOUNDARY')
            try:
                f.app.runtime.shutdown();self.assertTrue(f.advisory.active_work());self.assertFalse(f.advisory.accepting)
                self.assertEqual(f.app.runtime.state.read(),wanted)
                self.assertEqual(f.advisory.runtime.native_control(sid,'AUTO_POLICY_BOUNDARY'),boundary)
            finally:release.set()
            wait_for(lambda:not f.advisory.active_work());f.app.runtime.close()

    def test_agent_computation_worker_exit_recovers_without_identity_reset(self):
        from tests.agent_auto_fixture import AgentAutoFixture
        f=AgentAutoFixture(self.root);self.addCleanup(f.close)
        before=[x['tracking_session_id'] for x in f.agent.query()['sessions']]
        f.agent.worker.process.kill();f.agent.worker.process.wait(3)
        with self.assertRaises(Exception):f.sample()
        f.sample()
        self.assertEqual(before,[x['tracking_session_id'] for x in f.agent.query()['sessions']])
        self.assertIsNone(f.agent.worker.process.poll());self.assertEqual(len(f.provider.calls),0)
    def test_unknown_provider_completion_restart_does_not_resubmit(self):
        from tests.agent_auto_fixture import AgentAutoFixture
        from engines.live.advisory_repository import AdvisoryRuntimeRepository
        f=AgentAutoFixture(self.root);self.addCleanup(f.close);f.advance_native();original=f.provider.analyze
        def lost(*args,**kwargs):original(*args,**kwargs);raise SystemExit('isolated lost worker completion')
        with patch.object(f.provider,'analyze',side_effect=lost):
            with self.assertRaises(SystemExit):f.auto_cycle()
        self.assertEqual(len(f.provider.calls),1)
        f.advisory.runtime=AdvisoryRuntimeRepository(f.advisory.runtime.store)
        f.auto_cycle();self.assertEqual(len(f.provider.calls),1)
        self.assertIsNone(f.advisory.latest('bj920161'))

    def fixture(self):
        p=subprocess.Popen([sys.executable,'-B',str(ROOT/'tests/runtime_process_fixture.py'),str(self.root)],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def ready():
            if p.poll() is not None:raise AssertionError(p.stderr.read().decode("utf-8","replace"))
            return json.loads((self.root/'ready.json').read_text()) if (self.root/'ready.json').exists() else None
        info=wait_for(ready,20)
        def call(path,body=None,auth=False):
            r=urllib.request.Request(info['url']+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json',**({'Authorization':'Bearer isolated-test-token'} if auth else {})})
            with urllib.request.urlopen(r,timeout=5) as response:return json.load(response)
        def close():
            if p.poll() is None:call('/internal/shutdown',{},True);p.wait(15)
            errors=p.stderr.read().decode("utf-8","replace");p.stderr.close()
            self.assertEqual(p.returncode,0,errors)
            self.assertNotIn("Traceback",errors,errors)
        self.addCleanup(close)
        def evidence():
            try:return read_json(self.root/'evidence.json')
            except (FileNotFoundError,ValueError):return {}
        return call,evidence
    def test_premarket_enable_once_detached_real_loop_auto_and_notification(self):
        call,evidence=self.fixture();call('/api/live/listener/start',{})
        wait_for(lambda:evidence().get('loop',{}).get('reason')=='SOURCE_CONNECTION_ERROR')
        self.assertEqual(evidence()['calls'],0)
        # All UI/control clients now closed. The independent process receives new native facts only.
        atomic(self.root/'clock.json',{'phase':'open'})
        result=wait_for(lambda:(d if (d:=evidence()).get('messages')==1 else None))
        self.assertEqual(result['calls'],1);self.assertEqual(result['opinions'],1);self.assertTrue(result['cursor'])
        boundary=RuntimeState(self.root/'lab/data').read()['listener_revision']
        call('/api/live/listener/start',{});time.sleep(.8)
        self.assertEqual(evidence()['calls'],1);self.assertEqual(evidence()['messages'],1)
        self.assertEqual(RuntimeState(self.root/'lab/data').read()['listener_revision'],boundary)
    def test_premarket_stop_blocks_open(self):
        call,evidence=self.fixture();call('/api/live/listener/start',{});call('/api/live/listener/stop',{})
        atomic(self.root/'clock.json',{'phase':'open'});time.sleep(1.5)
        self.assertEqual(evidence()['calls'],0);self.assertEqual(evidence()['loop']['desired'],'DISABLED')
    def test_no_qualified_event_no_ai_and_internal_auth(self):
        call,evidence=self.fixture();call('/api/live/listener/start',{});atomic(self.root/'clock.json',{'phase':'clear'});time.sleep(.7)
        self.assertEqual(evidence()['calls'],0)
        with self.assertRaises(urllib.error.HTTPError) as e:call('/internal/shutdown',{})
        self.assertEqual(e.exception.code,403)

if __name__=='__main__':unittest.main()
