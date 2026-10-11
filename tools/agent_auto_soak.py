"""Real elapsed load test: TEST owner/native core + fixed production composition + Fake AI."""
from pathlib import Path
from datetime import datetime,timedelta
from threading import Thread
import argparse,hashlib,json,subprocess,sys,time,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from tests.test_market_agent import frame
from app.shell.bootstrap import build_application
from app.shell.server import make_server
from shared.config import Settings
from tools.runtime_closure_harness import memory

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=3600);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='agent-auto-soak-') as temp:
        base=Path(temp);f=AgentAutoFixture(base);f.app.live_loop.advisory._auto_pool.shutdown(wait=True)
        class Lifecycle:
            def status(self):return {'status':f.agent.query()['agent_state'],'identity':{'root':str(f.agent.root),'source':'TEST'}}
            def query(self):return f.agent.query()
        app=build_application(Settings(ROOT,data_root=base/'integration',source='TEST',test_run_id='agent-auto-soak'),
            advisory_provider=f.provider,agent_client=f.port,source_lifecycle=Lifecycle(),market_source_overrides={'market_agent_root':str(f.agent.root)})
        a=app.live_loop.advisory;a.clock=lambda:f.now;a.market_is_open=lambda _:True
        a.portfolio_context=lambda s:{'status':'NOT_INITIALIZED','ai_execution_mode':'ADVISORY_ONLY'}
        a.ingest();a.save_settings({'auto_ai_mode':'ALL_EVENTS','auto_event_types':['NEW_HIGH'],'debounce_seconds':3})
        started=time.monotonic();initial=f.now
        def frames():
            f.now=initial+timedelta(seconds=time.monotonic()-started);values={}
            for symbol,price in f.prices.items():
                value=frame(f.now,price+int((f.now-initial.replace(second=0,microsecond=0)).total_seconds()/300)*.5);bars=f.bars[symbol]
                for bar in value['dataset']['stockBars']:
                    if bar['time'] not in bars:bars[bar['time']]=bar
                value['dataset']['stockBars']=[bars[k] for k in sorted(bars)];value['dataset']['stockTradeBars']=value['dataset']['stockBars'];values[symbol]=value
            return values
        f.agent.start(frames,interval=5);app.live_loop.start(native_only=True)
        for r in app.routers:
            if hasattr(r,'start_read_model'):r.start_read_model(base/'integration/runtime/live/read_model/latest.json')
            if hasattr(r,'start_observation_model'):r.start_observation_model(base/'integration/runtime/live/observation_read_model/latest.json')
        server=make_server(app,0);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        runtime=next(r for r in app.routers if hasattr(r,'build_id'))
        code_paths=('engines/live/loop.py','engines/live/synchronization.py','engines/live/qualification.py','engines/live/advisory.py','engines/live/advisory_repository.py','bridges/market_agent.py','bridges/active_market_source.py','app/shell/bootstrap.py','app/shell/server.py','app/live/static/live.js','app/system/market_source.py','app/system/source_repository.py','tools/agent_auto_soak.py','tools/agent_auto_soak.js')
        url=f'http://127.0.0.1:{server.server_port}';(out/'instance.json').write_text(json.dumps({'url':url,'source':'TEST','real_provider_calls':0,'build_id':runtime.build_id,'code_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in code_paths}}))
        node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
        log=(out/'browser.log').open('w',encoding='utf-8');browser=subprocess.Popen([str(node),str(ROOT/'tools/agent_auto_soak.js'),url,str(out),str(args.seconds)],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        samples=[]
        try:
            while True:
                owner=f.agent.query();cards=a.stock_cards();opinions=[o for s in f.prices for o in a.history(s)]
                samples.append({'elapsed_seconds':time.monotonic()-started,'memory':memory(),'fact_count':len(owner['facts']),
                    'event_count':sum(x['kind']=='EVENT' for x in owner['facts']),'fake_calls':len(f.provider.calls),
                    'opinion_count':len(opinions),'opinion_triggers':sorted(set(o['trigger_type'] for o in opinions)),
                    'listener':app.live_loop.status,'listener_error':app.live_loop.last_error,
                    'cards':[{'symbol':c['session']['symbol'],'sync':c['sync'],'analysis_status':c['health'].get('analysis_status')} for c in cards]})
                (out/'samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({k:samples[-1][k] for k in ('elapsed_seconds','fact_count','event_count','fake_calls','opinion_count','listener_error')}),flush=True)
                if browser.poll() is not None:break
                time.sleep(30)
            result=json.loads((out/'browser.json').read_text());duration=result.get('elapsed_seconds',0)
            report={'status':'PASS' if browser.returncode==0 and samples[-1]['opinion_count']>=2 and samples[-1]['opinion_triggers']==['AUTO_EVENT'] and not any(s['listener_error'] for s in samples) else 'FAIL',
                'sustained_60_minutes':'PASS' if duration>=3600 else 'NOT_RUN_60_MINUTES','seconds':duration,'samples':len(samples),'real_provider_calls':0,
                'fake_calls':len(f.provider.calls),'final_opinions':samples[-1]['opinion_count'],'account_actions':0,'owner':'ACTUAL_TEST_AGENT_NATIVE_CORE','source':'FIXED_MARKET_AGENT'}
            (out/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
            return 0 if report['status']=='PASS' else 1
        finally:
            if browser.poll() is None:browser.terminate();browser.wait(10)
            log.close();app.live_loop.stop()
            if app.live_loop.thread:app.live_loop.thread.join(10)
            for r in app.routers:
                if hasattr(r,'close'):r.close()
            a._auto_pool.shutdown(wait=True);server.shutdown();server.server_close();thread.join(3);f.close()
if __name__=='__main__':raise SystemExit(main())
