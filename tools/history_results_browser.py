"""Isolated UX acceptance with real storage and Fake Provider. No network AI."""
import sys,tempfile,subprocess,time
from pathlib import Path
from threading import Thread
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from tests.test_history import Adapter,Provider,rows
from app.shell.server import make_server
from engines.history.bars import TZ
def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='history-results-') as tmp:
        f=AgentAutoFixture(Path(tmp));router=next(r for r in f.app.routers if type(r).__name__=='HistoryRouter')
        router.bars.adapter=Adapter(rows());router.bars.clock=lambda:datetime(2026,9,25,16,tzinfo=TZ)
        p=Provider();original=p.analyze_history
        def fake(*args):
            original(*args)
            return {'analysis':{'conclusion':'volume_context：ratio=0.72；amount=null。','basis':'成交量2354661股，不超过327.14万股，价格20.44元。','next_observation':'等待确认，不应猜测。','limitations':'成交额数据未提供。'}}
        p.analyze_history=fake;router.analysis.provider=p;router.analysis.name_resolver=lambda symbol:'测试股票'+symbol[-2:]
        for r in f.app.routers:
            if type(r).__name__=='ObservationRouter':r.client=f.port;r.active_source=None
        q=dict(end_date='2026-09-24',period='DAY',volume_period='WEEK',samples=20,limit=31,adjustment='NONE')
        for i,symbol in enumerate(('bj920161','sh688601','bj920161')):
            j=router.analysis.submit({**q,'symbol':symbol,'request_id':'browser-setup-'+str(i),'force_reanalysis':True})
            for _ in range(100):
                if router.store.job(j['id'])['status']=='SUCCEEDED':break
                time.sleep(.01)
        server=make_server(f.app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            code=subprocess.run([str(node),str(ROOT/'tools/history_results_browser.cjs'),f'http://127.0.0.1:{server.server_port}','--fake-write'],timeout=90).returncode
            assert len(p.inputs)==4, f'Expected 3 fixture calls + 1 explicit reanalysis; got {len(p.inputs)}'
            print('Fake Provider calls: 4; two default repeat submissions reused existing results.')
            return code
        finally:
            server.shutdown();server.server_close();thread.join(3)
            for r in f.app.routers:
                if hasattr(r,'close'):r.close()
            f.close()
if __name__=='__main__':raise SystemExit(main())
