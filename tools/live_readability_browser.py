"""Isolated saved Opinion/UI acceptance. Fake provider; no production writes."""
from pathlib import Path
from dataclasses import replace
from datetime import timedelta
from threading import Thread
import json,sys,tempfile,subprocess,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.support.native import NativeFixture
from app.shell.server import make_server


def main():
    out=ROOT/'artifacts/live_readability_20260921/browser';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='readability-browser-') as tmp:
        f=NativeFixture(Path(tmp));a=f.advisory;a.market_is_open=lambda _:True
        account=f.create('ADVISORY_ONLY');original=f.provider.analyze
        def rich(*args):
            value=original(*args);p=value['analysis']
            p.update(current_state='价格守住支撑，但量能确认仍不足。',game_state={'summary':'价格守住支撑，但量能确认仍不足。','buyer_state':'承接增强','seller_state':'卖方压力减弱'},
                     core_conflict='价格抬高与量能不足并存，不能把改善等同于确认。',
                     evidence=['价格 22.07 → 22.13，变化 +0.06。','alpha尚未转正。','特殊文本 <img src=x onerror=alert(1)> 只应作为文字展示。'],
                     next_observation_focus=[{'target':'观察VWAP','watch_for':'价格是否持续站稳','meaning':'确认支撑有效性'}],
                     invalidation=['跌破支撑则 INVALID；等待 WAIT，不追加仓位。'],
                     previous_hypothesis_review={'status':'STRENGTHENED','reason':'因此判定为STRENGTHENED而非CONFIRMED；当前量能仍不足。'})
            p['game_state'].update(absorption_state='吸收中',initiative_side='BUYER',supply_pressure='卖压减弱',demand_strength='需求改善',price_impact_state='推动有限')
            p['scenario_tree'][0].update(label='RECLAIM_CONTINUE',recommended_action='WAIT')
            return value
        f.provider.analyze=rich
        def append(price=22.13):
            f.append(price=price);f.native_observations[-1].update(alpha=.2 if price==22.07 else .1,volume_ratio=1.2)
            f.publish()
        append(22.07);a.analyze('bj920161')
        a.save_settings({'auto_ai_mode':'ALL_EVENTS','debounce_seconds':3});append()
        a.poll_auto();f.now+=timedelta(seconds=4);a.poll_auto()
        for _ in range(200):
            if len(a.history('bj920161'))==2:break
            time.sleep(.025)
        assert a.latest('bj920161')['trigger_type']=='AUTO_EVENT'
        a.save_settings({'auto_ai_mode':'OFF'})
        router=next(r for r in f.app.routers if type(r).__name__=='LiveRouter')
        router.start_read_model(Path(tmp)/'read_model/live.json')
        class Control:
            def accepts_post(self,path):return path in ('/test/append','/test/failure-state')
            def route(self,method,path,payload=None):
                if path=='/test/info':return 200,{'calls':len(f.provider.calls),'latest':a.latest('bj920161'),
                    'cursor':a.runtime.cursor(f.members['bj920161']['tracking_session_id']),
                    'ledger_count':len(f.p.engine.ledger(account['account_id']))},None
                if path=='/test/append':append(22.2);return 200,{'status':'TEST_APPENDED'},None
                return None
        app=replace(f.app,routers=(Control(),*f.app.routers));server=make_server(app,0)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node=Path(__import__('os').environ.get('TRADING_LAB_NODE', str(ROOT/'.dev/runtime/node/node.exe')))
            return subprocess.run([str(node),str(ROOT/'tools/live_readability_e2e.js'),f'http://127.0.0.1:{server.server_port}',str(out)],timeout=180).returncode
        finally:router.close();server.shutdown();server.server_close();thread.join(3);f.close()


if __name__=='__main__':raise SystemExit(main())
