"""Small isolated application/browser check; Fake AI, TEST Agent, no backups."""
import subprocess,sys,tempfile
from pathlib import Path
from threading import Thread
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from app.shell.server import make_server

def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='product-smoke-') as tmp:
        f=AgentAutoFixture(Path(tmp));f.advisory.analyze('bj920161')
        server=make_server(f.app,0);thread=Thread(target=server.serve_forever,daemon=True)
        for router in f.app.routers:
            if hasattr(router,'start_read_model'):router.start_read_model(Path(tmp)/'live-read.json')
            if hasattr(router,'start_observation_model'):router.start_observation_model(Path(tmp)/'observation-read.json')
        thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/product_smoke.cjs'),f'http://127.0.0.1:{server.server_port}'],timeout=60).returncode
        finally:server.shutdown();server.server_close();thread.join(3);f.close()

if __name__=='__main__':raise SystemExit(main())
