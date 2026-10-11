"""Candidate-only synthetic integration and injected lifecycle failure probes."""
from pathlib import Path
import json,os,socket,subprocess,sys
PACKAGE=Path(sys.argv[1]).resolve();PROJECT=Path(sys.argv[2]).resolve();OUT=PROJECT/'.dev/step04';CORE=PACKAGE/'TradingLab'
sys.path[:0]=[str(CORE),str(PROJECT),str(PACKAGE)]
os.environ['TRADING_LAB_NODE']=str(PACKAGE/'runtime/node/node.exe')

def fake_chain():
 import ipaddress
 def guard(event,args):
  if event=='socket.getaddrinfo' and args[0] not in ('localhost','127.0.0.1','::1',None):raise PermissionError('External network denied')
  if event=='socket.connect' and isinstance(args[1],tuple) and not ipaddress.ip_address(args[1][0]).is_loopback:raise PermissionError('External network denied')
  if event=='open':
   path,mode,flags=args
   if isinstance(path,int):return
   if ((isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)) and str(path).lower()!='nul':
    if not Path(path).resolve().is_relative_to(OUT):raise PermissionError('Write outside STEP04')
 sys.addaudithook(guard)
 import tests.support.native as native
 native.ROOT=CORE
 from tests.agent_auto_fixture import AgentAutoFixture
 from adapters.telegram import load_config
 f=AgentAutoFixture(CORE/'sandbox/fake-chain')
 try:
  f.advance_native();f.auto_cycle();opinion=f.advisory.latest('bj920161')
  assert opinion and opinion['trigger_type']=='AUTO_EVENT'
  assert len(f.provider.calls)==1
  frozen=f.advisory.opinions.input(opinion['input_id']);assert frozen['portfolio_context']['ai_execution_mode']=='ADVISORY_ONLY'
  assert load_config(CORE,'TEST').state=='DISABLED'
  import app.shell.bootstrap,engines.live.market_agent.service
  assert Path(app.shell.bootstrap.__file__).is_relative_to(CORE) and Path(engines.live.market_agent.service.__file__).is_relative_to(CORE)
  result={'status':'PASS','candidate':str(PACKAGE),'worker_executable':str(PACKAGE/'runtime/node/node.exe'),'business_modules_from_candidate':True,'fake_provider_calls':1,'trigger':'AUTO_EVENT','execution':'ADVISORY_ONLY','telegram':'DISABLED','external_network':'DENIED_BY_AUDIT_HOOK','native_observations':len(f.bridge.advisory_facts('bj920161')['observations'])}
 finally:f.close()
 print(json.dumps(result,ensure_ascii=False))

def rollback():
 from unittest.mock import patch
 import portable_test_control as control
 from adapters.runtime_platform import alive
 original=subprocess.Popen
 def injected(args,*a,**kw):
  if isinstance(args,list) and 'trading_lab.py' in args:raise OSError('STEP04_INJECTED_WEB_SPAWN_FAILURE')
  return original(args,*a,**kw)
 try:
  with patch.object(subprocess,'Popen',injected):control.start()
 except OSError as e:assert 'STEP04_INJECTED' in str(e)
 else:raise AssertionError('Expected injected failure')
 state=json.loads((CORE/'sandbox/instances.json').read_text('utf-8'));assert state['stopped'] and not alive(state['agent'])
 assert control.port_available(control.CFG['agent_port']) and control.port_available(control.CFG['web_port'])
 print(json.dumps({'status':'PASS','fault':'Web Popen fails after real Agent start','agent_was_started':True,'rollback':'authenticated graceful shutdown plus owned job cleanup','ports_free':True}))

if __name__=='__main__':{'fake':fake_chain,'rollback':rollback}[sys.argv[3]]()
