"""Actual CLI processes in isolated TEST roots. No network market or Provider."""
from pathlib import Path
from contextlib import contextmanager
import json,os,subprocess,sys,tempfile,time,unittest,urllib.request,urllib.error
ROOT=Path(__file__).resolve().parents[1]
class AgentOnlyStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='agent-startup-');self.base=Path(self.tmp.name);self.processes=[];self.logs=[]
    def tearDown(self):
        for p in reversed(self.processes):
            if p.poll() is None:p.terminate();p.wait(15)
        for log in self.logs:log.close()
        self.tmp.cleanup()
    def spawn(self,args,env=None):
        log=(self.base/('process-'+str(len(self.processes))+'.log')).open('w',encoding='utf-8');self.logs.append(log)
        p=subprocess.Popen([sys.executable,'-B',*args],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.processes.append(p);return p
    def get(self,url):
        try:
            with urllib.request.urlopen(url,timeout=8) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def web(self):
        env={k:v for k,v in os.environ.items() if not k.startswith('TRADING_LAB_')}
        env.update(TRADING_LAB_SOURCE='TEST',TRADING_LAB_DATA_ROOT=str(self.base/'data'),TRADING_LAB_TEST_RUN_ID='fixed-source-startup',TRADING_LAB_V2A_WORKSPACE=str(self.base/'old-workspace'),TRADING_LAB_LIVE_SOURCE='V2A_WORKSPACE')
        p=self.spawn(['trading_lab.py','--port','0','--market-source','V2A_WORKSPACE','--market-agent-root',str(self.base/'agent')],env)
        record=self.base/'data/runtime/web-instance.json'
        for _ in range(150):
            if p.poll() is not None:self.fail('isolated CLI exited; inspect '+str(self.base))
            if record.exists():
                value=json.loads(record.read_text())
                try:
                    if self.get(value['url']+'/healthz')[0]==200:return p,value['url']
                except OSError:pass
            time.sleep(.1)
        self.fail('CLI not ready')
    def test_cli_no_old_workspace_agent_unavailable_and_retired_urls(self):
        p,url=self.web();code,value=self.get(url+'/api/system/market-source');self.assertEqual(code,200)
        self.assertEqual(value['active_market_source'],'MARKET_AGENT');self.assertEqual(value['status'],'UNAVAILABLE')
        for endpoint in ('cutover','rollback','recover','legacy-trackers','preflight'):
            self.assertEqual(self.get(url+'/api/system/market-source/'+endpoint)[0],404)
        self.assertFalse((self.base/'old-workspace').exists())
        p.terminate();p.wait(10);before=(self.base/'data/system/market-source.json').read_bytes()
        p,url=self.web();self.assertEqual((self.base/'data/system/market-source.json').read_bytes(),before)
        self.assertEqual(self.get(url+'/api/live/runtime-version')[1]['source_owner'],'MARKET_DATA_AGENT')
    def test_actual_agent_reconnect_single_writer_and_same_data_identity(self):
        self.spawn(['market_data_agent.py','--data-root',str(self.base/'agent'),'--source','TEST','--start-paused'])
        from bridges.market_agent import AgentClient
        client=AgentClient(self.base/'agent','TEST')
        for _ in range(100):
            try:value=client.query();break
            except Exception:time.sleep(.1)
        else:self.fail('Agent unavailable')
        p,url=self.web();before=self.get(url+'/api/system/market-source')[1]
        self.assertIn('identity',before['agent']);self.assertEqual(before['source_owner'],'MARKET_DATA_AGENT')
        duplicate=self.spawn(['market_data_agent.py','--data-root',str(self.base/'agent'),'--source','TEST','--start-paused']);self.assertNotEqual(duplicate.wait(15),0)
        old_pid=value['agent_identity']['pid'];client.request('/v1/shutdown',{'confirm':'STOP_DATA_SERVICE'});self.processes[0].wait(15)
        self.spawn(['market_data_agent.py','--data-root',str(self.base/'agent'),'--source','TEST','--start-paused'])
        for _ in range(100):
            try:
                if client.query()['agent_identity']['pid']!=old_pid:break
            except Exception:pass
            time.sleep(.1)
        after=self.get(url+'/api/system/market-source')[1]
        self.assertEqual(before['source_generation'],after['source_generation']);self.assertEqual(before['source_root'],after['source_root']);self.assertNotEqual(after['agent']['identity']['pid'],old_pid)
        (self.base/'old-workspace').mkdir();(self.base/'old-workspace/events.jsonl').write_text('old change')
        self.assertEqual(self.get(url+'/api/system/market-source')[1]['agent']['identity']['pid'],after['agent']['identity']['pid'])
