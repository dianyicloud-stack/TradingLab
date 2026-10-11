"""One fixed Agent capability shared by Live, quotes and observation."""
from threading import RLock
from contextlib import contextmanager,nullcontext
from shared.logging.timing import measured_lock
class ActiveMarketSource:
    def __init__(self,agent,config):
        self.agent=agent;self.lock=RLock();self.generation=config['source_generation'];self.agent_root=config.get('market_agent_root')
        self.agent.data_generation=self.generation
    @property
    def mode(self):return 'MARKET_AGENT'
    @property
    def current(self):return self.agent
    def identity(self):return {'source_owner':'MARKET_DATA_AGENT','source_root':self.agent_root,'source_generation':self.generation}
    @contextmanager
    def read_scope(self):
        with measured_lock(self.lock):
            with self.agent.snapshot_scope() if hasattr(self.agent,'snapshot_scope') else nullcontext():yield
    def __getattr__(self,name):return getattr(self.agent,name)
    def observation_state(self):
        with self.lock:return {**self.agent.client.query(),**self.identity()}
    def agent_command(self,method,payload):
        with self.lock:return getattr(self.agent.client,method)(payload)
