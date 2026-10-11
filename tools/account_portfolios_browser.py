"""Isolated real API/UI acceptance. No external AI or Telegram."""
import sys,tempfile,subprocess
from pathlib import Path
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from app.shell.server import make_server

def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='portfolio-ui-') as tmp:
        f=AgentAutoFixture(Path(tmp))
        for router in f.app.routers:
            if type(router).__name__=='ObservationRouter':router.client=f.port;router.active_source=None
        server=make_server(f.app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            result=subprocess.run([str(node),str(ROOT/'tools/account_portfolios_browser.cjs'),f'http://127.0.0.1:{server.server_port}'],timeout=90)
            assert not f.provider.calls
            assert all(not f.p.engine.state(a['account_id'])['executions'] for a in f.p.catalog())
            return result.returncode
        finally:server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
