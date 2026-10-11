"""TEST-only fixed Agent UI acceptance; events created by the native owner."""
from pathlib import Path
from dataclasses import replace
from datetime import timedelta
from threading import Thread
import json,subprocess,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from app.shell.bootstrap import build_application
from app.shell.server import make_server
from shared.config import Settings
def main():
    out=ROOT/'artifacts/m2_auto_agent_closure/c-browser';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='auto-agent-browser-') as tmp:
        base=Path(tmp);f=AgentAutoFixture(base);f.advisory._auto_pool.shutdown(wait=True)
        class Lifecycle:
            def status(self):return {'status':'RUNNING','identity':{'source':'TEST'}}
        app=build_application(Settings(ROOT,data_root=base/'integration',source='TEST',test_run_id='auto-agent-browser'),advisory_provider=f.provider,
            agent_client=f.port,source_lifecycle=Lifecycle(),market_source_overrides={'market_agent_root':str(f.agent.root)})
        a=app.live_loop.advisory;anchor=[time.monotonic()];a.clock=lambda:f.now+timedelta(seconds=time.monotonic()-anchor[0]);a.market_is_open=lambda _:True
        a.portfolio_context=lambda s:{'status':'NOT_INITIALIZED','ai_execution_mode':'ADVISORY_ONLY'}
        a.ingest();a.save_settings({'auto_ai_mode':'ALL_EVENTS','auto_event_types':['NEW_HIGH'],'debounce_seconds':3})
        class Control:
            def accepts_post(self,path):return path=='/test/advance'
            def route(self,method,path,payload=None):
                if path=='/test/advance' and method=='POST':
                    symbol=(payload or {}).get('symbol','bj920161');f.advance_native(symbol);anchor[0]=time.monotonic();return 200,{'date':f.now.isoformat()},None
                if path=='/test/info':return 200,{'calls':len(f.provider.calls),'opinions':{s:a.latest(s) for s in f.prices},'settings':{s:a.effective(s) for s in f.prices}},None
                return None
        app=replace(app,routers=(Control(),*app.routers))
        for r in app.routers:
            if hasattr(r,'start_read_model'):r.start_read_model(base/'integration/runtime/live/read_model/latest.json')
            if hasattr(r,'start_observation_model'):r.start_observation_model(base/'integration/runtime/live/observation_read_model/latest.json')
        server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
        try:return subprocess.run([str(node),str(ROOT/'tools/agent_auto_browser.js'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=240).returncode
        finally:
            app.live_loop.stop()
            if app.live_loop.thread:app.live_loop.thread.join(10)
            for r in app.routers:
                if hasattr(r,'close'):r.close()
            a._auto_pool.shutdown(wait=True);server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
