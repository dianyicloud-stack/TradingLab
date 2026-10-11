"""Isolated owner-backed deletion acceptance; no real source or provider."""
from pathlib import Path
from threading import Thread
from dataclasses import replace
import sys,tempfile,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from tests.test_market_agent import LocalPort,frame
from engines.live.market_agent.service import AgentService
from bridges.market_agent import AgentFactBridge
from app.live.observation import ObservationRouter
from app.live.tracking_delete import LiveTrackingDeletion
from app.shell.server import make_server

def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='delete-browser-') as tmp:
        f=NativeFixture(Path(tmp)/'lab');f.now=f.now.replace(hour=9,minute=35,second=40)
        agent=AgentService(Path(tmp)/'agent',clock=lambda:f.now,calendar=lambda _:True)
        try:
            port=LocalPort(agent);bridge=AgentFactBridge(port)
            f.advisory.workspace=bridge;f.app.live_loop.workspace=bridge
            symbols=['bj920161','sh688601','sz301111','sz300504']
            for index,symbol in enumerate(symbols):agent.command({'schema_version':'1.0','source':'TEST','action':'ADD','symbol':symbol,'name':'TEST '+symbol,'board':{'code':'BKTEST','name':'TEST'},'command_id':'add-'+symbol,'expected_version':index})
            agent.cycle({s:frame(f.now) for s in symbols})
            deletion=LiveTrackingDeletion(port,f.advisory,lambda _:[],lambda:[],lambda:[])
            observation=ObservationRouter(port,f.advisory.latest,deletion=deletion)
            app=replace(f.app,routers=(observation,*f.app.routers));server=make_server(app,0)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
                return subprocess.run([str(node),str(ROOT/'tools/tracking_delete_browser.cjs'),f'http://127.0.0.1:{server.server_port}'],timeout=120).returncode
            finally:server.shutdown();server.server_close();thread.join(3)
        finally:agent.close();f.close()

if __name__=='__main__':raise SystemExit(main())
