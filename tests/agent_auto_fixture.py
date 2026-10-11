"""Actual TEST Agent/bridge/listener with native-generated facts and Fake AI."""
from datetime import datetime,timedelta
from tests.support.native import NativeFixture
from tests.test_market_agent import LocalPort,frame
from engines.live.market_agent.service import AgentService
from bridges.market_agent import AgentFactBridge

class AgentAutoFixture(NativeFixture):
    def __init__(self,root):
        super().__init__(root/'lab')
        self.now=datetime.fromisoformat('2026-09-18T09:35:40+08:00')
        self.agent=AgentService(root/'agent',clock=lambda:self.now,calendar=lambda _:True)
        self.agent.repo.clock=lambda:self.now
        self.port=LocalPort(self.agent);self.bridge=AgentFactBridge(self.port)
        self.advisory.workspace=self.bridge;self.app.live_loop.workspace=self.bridge
        self.advisory.market_is_open=lambda _:True
        self.add_agent('bj920161');self.add_agent('sh688601')
        self.prices={'bj920161':10,'sh688601':15};self.bars={};self.sample()
        self.advisory.ingest()
        self.advisory.save_settings({'auto_ai_mode':'ALL_EVENTS','auto_event_types':['NEW_HIGH'],'debounce_seconds':3})
        self.advisory.portfolio_context=lambda s:{'status':'NOT_INITIALIZED','ai_execution_mode':'ADVISORY_ONLY'}
    def add_agent(self,symbol):
        self.agent.command({'schema_version':'1.0','source':'TEST','action':'ADD','command_id':'add-'+symbol,
            'expected_version':self.agent.query()['version'],'symbol':symbol,'name':'TEST '+symbol,'board':{'code':'BKTEST','name':'TEST'}})
    def sample(self):
        frames={}
        for symbol,price in self.prices.items():
            value=frame(self.now,price);bars=self.bars.setdefault(symbol,{})
            for bar in value['dataset']['stockBars']:
                # Earlier bars remain immutable; later cycles append new facts.
                if bar['time'] not in bars:bars[bar['time']]=bar
            value['dataset']['stockBars']=[bars[k] for k in sorted(bars)]
            value['dataset']['stockTradeBars']=value['dataset']['stockBars']
            frames[symbol]=value
        self.agent.cycle(frames)
    def advance_native(self,symbol='bj920161',delta=1):
        self.now+=timedelta(minutes=5);self.prices[symbol]+=delta;self.sample()
    def auto_cycle(self):
        self.app.live_loop.poll();self.now+=timedelta(seconds=4);self.app.live_loop.poll()
    def close(self):
        if hasattr(self,'agent'):self.agent.close()
        super().close()
