"""Separate TEST producer process. Recorded deterministic raw inputs, no network."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timedelta
from engines.live.market_agent.service import AgentService
from market_data_agent import serve
from adapters.runtime_lease import runtime_lease
from tests.test_market_agent import frame

def main():
    root=Path(sys.argv[1]).resolve();now=datetime.fromisoformat('2026-09-16T09:34:55+08:00')
    with runtime_lease(root):
        service=AgentService(root,source='TEST',calendar=lambda _:True,clock=lambda:now)
        def source():
            nonlocal now
            now+=timedelta(seconds=15);values={}
            for i,symbol in enumerate(('bj920161','sh688696','sz300225')):
                price=10+i+(now.minute%10)*.03;item=frame(now,price)
                bars=[];minute=now.replace(hour=9,minute=30,second=0)
                while minute<=now:
                    p=10+i+(minute.minute%10)*.03;bars.append({'date':now.date().isoformat(),'time':minute.strftime('%H:%M:%S'),'open':p,'close':p,'high':p+.01,'low':p-.01,'volume':1000,'amount':p*1000});minute+=timedelta(minutes=1)
                item['dataset']['stockBars']=bars;item['dataset']['stockTradeBars']=bars;values[symbol]=item
            return values
        server=serve(service,root);service.start(source,interval=.35)
        try:server.serve_forever()
        finally:server.server_close();service.close()
if __name__=='__main__':main()
