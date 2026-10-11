"""Wall-clock paired browser soak. TEST namespace, copied prose, Fake provider only."""
from pathlib import Path
from dataclasses import replace
from threading import Thread,Event
import json,sys,tempfile,subprocess,time,sqlite3,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server

def main():
    name=sys.argv[2] if len(sys.argv)>2 else 'soak'
    if not name.replace('-','').isalnum():raise ValueError('Invalid isolated output name')
    out=ROOT/'artifacts/lifecycle_20260921'/name;out.mkdir(parents=True,exist_ok=True)
    duration=int(sys.argv[1]) if len(sys.argv)>1 else 3600
    db=sqlite3.connect((ROOT/'data/live/advisory/advisory.db').as_uri()+'?mode=ro',uri=True)
    samples={}
    for (raw,) in db.execute("select payload from advisory_opinions where session_date='2026-09-21'"):
        v=json.loads(raw);s=v['symbol']
        if s not in samples or len(raw)>samples[s][0]:samples[s]=(len(raw),v)
    db.close()
    fields=('current_state','game_state','core_conflict','evidence','next_observation_focus','invalidation','scenario_tree','key_levels')
    prose=[{k:v[1][k] for k in fields if k in v[1]} for v in samples.values()][:3]
    assert len(prose)==3
    (out/'sample-measurements.json').write_text(json.dumps({'copied_fields':fields,'prose_bytes':[len(json.dumps(p,ensure_ascii=False).encode()) for p in prose],'real_provider_calls':0},ensure_ascii=False,indent=2),encoding='utf-8')
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='lifecycle-soak-') as tmp:
        f=NativeFixture(Path(tmp));f.add_symbol('sz300474','测试丙');a=f.advisory;symbols=list(f.members)
        original=f.provider.analyze;current=[0]
        def rich(*args):
            v=original(*args);v['analysis'].update(copy.deepcopy(prose[symbols.index(args[0]['symbol'])%3]));return v
        f.provider.analyze=rich;a.market_is_open=lambda _:True
        # Current production day: 9/13/9 opinions; use 30 each to include growth.
        for n in range(30):
            for i,s in enumerate(symbols):
                current[0]=i;f.append(s,price=20+i+n/100);a.analyze(s)
        a.save_settings({'auto_ai_mode':'OFF'})
        router=next(r for r in f.app.routers if type(r).__name__=='LiveRouter');router.start_read_model(Path(tmp)/'view.json')
        class Baseline:
            def accepts_post(self,path):return False
            def route(self,method,path,payload=None):
                if path=='/assets/live-baseline.js':return 200,(ROOT/'artifacts/lifecycle_20260921/before/app/live/static/live.js').read_bytes(),'text/javascript'
                if path=='/assets/live-baseline.css':return 200,(ROOT/'artifacts/lifecycle_20260921/before/app/live/static/live.css').read_bytes(),'text/css'
                return None
        server=make_server(replace(f.app,routers=(Baseline(),*f.app.routers)),0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        stop=Event();errors=[]
        def grow():
            while not stop.wait(45):
                try:
                    for i,s in enumerate(symbols):current[0]=i;f.append(s,price=21+i);a.analyze(s)
                except Exception as e:errors.append(type(e).__name__+':'+str(e))
        publisher=Thread(target=grow,daemon=True);publisher.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            result=subprocess.run([str(node),str(ROOT/'tools/lifecycle_soak.cjs'),f'http://127.0.0.1:{server.server_port}',str(out),str(duration)],timeout=duration+300)
            (out/'producer.json').write_text(json.dumps({'errors':errors,'fake_calls':len(f.provider.calls),'real_provider_calls':0,'final_opinions':a.opinions.count()}),encoding='utf-8')
            return result.returncode
        finally:stop.set();publisher.join(30);router.close();server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
