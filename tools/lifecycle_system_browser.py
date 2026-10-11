"""Real System maintenance UI against isolated owner contracts; no cleanup enable."""
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from threading import Thread
from tempfile import TemporaryDirectory
import sys,json,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server

def main():
    out=ROOT/'artifacts/lifecycle_20260921/system-browser';out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=ROOT/'tests',prefix='maintenance-browser-') as tmp:
        f=NativeFixture(Path(tmp));m=next(r.service for r in f.app.routers if type(r).__name__=='MaintenanceRouter');calls=[]
        def query():calls.append('query');return {'source':'TEST','capabilities':['DAILY_RETENTION_V1','RETENTION_VALIDATION_V2']}
        def command(p):
            assert p['action']=='RETENTION_PREVIEW';calls.append(p['action']);return {'keep_day':'2026-09-09','blocked':False,'records':0,'estimated_logical_bytes':0,'protected_sessions':[]}
        m.agent=SimpleNamespace(root=Path(tmp)/'agent',query=query,command=command);m.start()
        class Evidence:
            def accepts_post(self,path):return False
            def route(self,method,path,payload=None):
                if path=='/test/evidence':return 200,{'owner_reads':len(calls),'provider_calls':len(f.provider.calls),'policy_enabled':m.policy['enabled']},None
                return None
        server=make_server(replace(f.app,routers=(Evidence(),*f.app.routers)),0);t=Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/lifecycle_system_browser.cjs'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=60).returncode
        finally:m.close();server.shutdown();server.server_close();t.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
