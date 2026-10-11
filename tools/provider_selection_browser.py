"""Isolated UI/API acceptance. Provider generations are always Fake."""
import sys,tempfile,subprocess,json
from pathlib import Path
from threading import Thread
from dataclasses import replace
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from tests.test_history import Adapter,rows
from app.shell.server import make_server
from shared.config import ScopedStore
from adapters.ai.advisory import AdvisoryProvider
from app.system.ai_configuration import AIConfiguration,AIConfigurationRouter
from engines.history.bars import TZ
from engines.history.service import evidence,SCHEMA

class Fake(AdvisoryProvider):
    def __init__(self):super().__init__(ROOT);self.calls=[]
    def catalog(self):
        c=super().catalog()
        for p in c['providers']:p['error']=None
        return c
    def analyze_history(self,frozen,*args):
        evidence(frozen,args[3],args[4]);self.calls.append(frozen)
        return {'analysis':{k:'隔离测试：只描述已提供的市场证据，不构成交易。' for k in SCHEMA['required']},'provider_attempt_count':1}

def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='provider-ui-') as tmp:
        f=AgentAutoFixture(Path(tmp));fake=Fake()
        owner=AIConfiguration(ScopedStore(Path(tmp)/'system',boundary=Path(tmp)),fake,f.advisory.catalog()['global'])
        f.advisory.provider.catalog=fake.catalog;f.advisory.model_configuration=owner
        for r in f.app.routers:
            if type(r).__name__=='ObservationRouter':r.client=f.port;r.active_source=None
        h=next(r for r in f.app.routers if type(r).__name__=='HistoryRouter')
        h.bars.adapter=Adapter(rows());h.bars.clock=lambda:datetime(2026,9,25,16,tzinfo=TZ)
        h.analysis.provider=fake;h.analysis.model_configuration=owner
        app=replace(f.app,routers=f.app.routers+(AIConfigurationRouter(owner),))
        server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            result=subprocess.run([str(node),str(ROOT/'tools/provider_selection_browser.cjs'),f'http://127.0.0.1:{server.server_port}'],timeout=100)
            assert len(fake.calls)==1, len(fake.calls)
            assert not f.provider.calls
            return result.returncode
        finally:
            server.shutdown();server.server_close();thread.join(5)
            for r in f.app.routers:
                if hasattr(r,'close'):r.close()
            f.close()
if __name__=='__main__':raise SystemExit(main())
