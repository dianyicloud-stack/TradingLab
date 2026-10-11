from pathlib import Path
from threading import Thread
from datetime import datetime
import tempfile,subprocess,json,time,sys,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from bridges.market_agent import AgentClient,AgentFactBridge
from app.shell.bootstrap import build_application
from app.shell.server import make_server
from shared.config import Settings
from tests.support.provider import PlanProvider

def main():
    out=Path(os.environ.get('TRADING_LAB_ACCEPTANCE_OUTPUT',ROOT/'artifacts/market_agent/browser'));out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='agent-browser-') as tmp:
        base=Path(tmp);root=base/'agent';root.mkdir();log=(out/'agent-process.log').open('w',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'-B',str(ROOT/'tests/market_agent_fixture_process.py'),str(root)],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        client=AgentClient(root,source='TEST')
        for _ in range(80):
            try:client.query();break
            except Exception:time.sleep(.1)
        app=build_application(Settings(ROOT,data_root=base/'data',source='TEST',test_run_id='market-agent-browser'),live_bridge=AgentFactBridge(client),advisory_provider=PlanProvider(),agent_client=client)
        service=app.live_loop.advisory
        service.clock=lambda:datetime.fromisoformat(client.query()['last_cycle_at'] or '2026-09-16T09:34:55+08:00');service.market_is_open=lambda _:True
        app.live_loop.interval=.1
        for router in app.routers:
            if hasattr(router,'start_read_model'):router.start_read_model(base/'data/runtime/live/read_model/latest.json')
            if hasattr(router,'start_observation_model'):router.start_observation_model(base/'data/runtime/live/observation_read_model/latest.json')
        server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            result=subprocess.run([str(node),str(ROOT/'tools/market_agent_e2e.mjs'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=180)
            (out/'final-agent-state.json').write_text(json.dumps(client.query(),ensure_ascii=False,indent=2),encoding='utf-8')
            return result.returncode
        finally:
            app.live_loop.stop()
            for router in app.routers:
                if hasattr(router,'close'):router.close()
            if app.live_loop.thread:app.live_loop.thread.join(5)
            server.shutdown();server.server_close();thread.join(3)
            try:client.request('/v1/shutdown',{'confirm':'STOP_DATA_SERVICE'})
            except Exception:process.terminate()
            process.wait(timeout=15);log.close()
if __name__=='__main__':raise SystemExit(main())
