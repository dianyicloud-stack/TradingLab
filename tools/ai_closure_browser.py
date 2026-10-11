"""Round 2 real browser, isolated TEST facts/runtime/account and fake AI only."""
from pathlib import Path
from threading import Thread
from dataclasses import replace
from unittest.mock import patch
import sys,json,tempfile,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server
from contracts.live.bridge import BridgeError
from contracts.live.advisory import AdvisoryProviderFailure

def main():
    out=ROOT/'artifacts/m2_ai_closure/browser';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='ai-closure-browser-') as tmp:
        f=NativeFixture(Path(tmp));f.advisory.market_is_open=lambda _:True
        account=f.create('ADVISORY_ONLY');f.provider.action='OPEN'
        for symbol in f.members:f.append(symbol)
        f.advisory.analyze('bj920161')
        fail_next={'value':False}
        original_analyze=f.provider.analyze
        def fake_analyze(*args,**kwargs):
            if fail_next['value']:
                fail_next['value']=False
                raise AdvisoryProviderFailure({'stage':'PROVIDER','error_code':'MODEL_INVALID',
                    'http_status':400,'retryable':False,'provider_invoked':True,
                    'provider_attempt_count':1,'transport_exception_type':'BadRequestError'})
            return original_analyze(*args,**kwargs)
        f.provider.analyze=fake_analyze
        class Control:
            def accepts_post(self,path):return path.startswith('/test/')
            def route(self,method,path,payload=None):
                # This harness owns native TEST facts, not a separate Agent process.
                if path=='/api/data-observation/state':return 200,{'status':'NOT_CONFIGURED','message':'隔离 Live 测试未配置独立行情 Agent。'},None
                if path=='/test/info':return 200,{'calls':len(f.provider.calls),'opinions':{s:f.advisory.latest(s) for s in f.members},
                    'cursors':{s:f.advisory.runtime.cursor(m['tracking_session_id']) for s,m in f.members.items()},
                    'ledger_count':len(f.p.engine.ledger(account['account_id']))},None
                if path=='/test/new-opinion':
                    f.append(payload.get('symbol','bj920161'));op=f.advisory.analyze(payload.get('symbol','bj920161'))
                    return 200,{'id':op['advisory_id']},None
                if path=='/test/failure':
                    f.append()
                    with patch.object(f.provider,'analyze',side_effect=TimeoutError('TEST secret')):
                        try:f.advisory.analyze('bj920161')
                        except BridgeError:pass
                    return 200,{'status':'TEST_FAILURE_RECORDED'},None
                if path=='/test/fail-next':
                    f.append();fail_next['value']=True
                    return 200,{'status':'NEXT_TEST_ANALYSIS_WILL_FAIL'},None
                return None
        app=replace(f.app,routers=(Control(),*f.app.routers));server=make_server(app,0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/ai_closure_browser.js'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=240).returncode
        finally:server.shutdown();server.server_close();thread.join(3);f.close()

if __name__=='__main__':raise SystemExit(main())
