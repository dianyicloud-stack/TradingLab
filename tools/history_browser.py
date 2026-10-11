"""Isolated actual UI chain with Fake history provider; never production AI."""
import sys,tempfile,subprocess
from pathlib import Path
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from tests.test_history import Adapter,Provider,rows
from app.shell.server import make_server
def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='history-browser-') as tmp:
        f=AgentAutoFixture(Path(tmp));router=next(r for r in f.app.routers if type(r).__name__=='HistoryRouter')
        router.bars.adapter=Adapter(rows());router.analysis.provider=Provider()
        for r in f.app.routers:
            if type(r).__name__=='ObservationRouter':r.client=f.port;r.active_source=None
        server=make_server(f.app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/history_browser.cjs'),f'http://127.0.0.1:{server.server_port}','--analyze'],timeout=60).returncode
        finally:
            server.shutdown();server.server_close();thread.join(3)
            for r in f.app.routers:
                if hasattr(r,'close'):r.close()
            f.close()
if __name__=='__main__':raise SystemExit(main())
