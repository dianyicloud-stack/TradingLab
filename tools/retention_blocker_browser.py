from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
import os,sys,subprocess,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server
def main():
    out=ROOT/'artifacts/retention_blockers/browser';out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=ROOT/'tests',prefix='retention-ui-') as tmp:
        root=Path(tmp);f=NativeFixture(root/'data');m=next(r.service for r in f.app.routers if type(r).__name__=='MaintenanceRouter');m.inventory_root=root
        bad=root/'tests/inaccessible';bad.mkdir(parents=True);agentroot=root/'agent';agentroot.mkdir();calls=[]
        def query():calls.append(1);return {'source':'TEST','capabilities':['DAILY_RETENTION_V1','RETENTION_VALIDATION_V2']}
        m.agent=SimpleNamespace(root=agentroot,query=query,command=lambda p:{'blocked':True,'reason':'NEW_DAY_OR_LOOKBACK_NOT_READY','validation':{'status':'FAILED','missing':[{'symbol':'bj920161','code':'VOLUME_HISTORY_MISSING'}]}})
        original=os.scandir
        def scan(p):
            if Path(p)==bad:raise PermissionError('isolated denial')
            return original(p)
        class Evidence:
            def accepts_post(self,p):return False
            def route(self,method,path,payload=None):
                if path=='/test/evidence':return 200,{'reads':len(calls),'provider_calls':len(f.provider.calls),'enabled':m.policy['enabled']},None
        with patch('os.scandir',side_effect=scan):
            m.run_once();server=make_server(replace(f.app,routers=(Evidence(),*f.app.routers)),0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
                return subprocess.run([str(node),str(ROOT/'tools/retention_blocker_browser.cjs'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=60).returncode
            finally:server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
