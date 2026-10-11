"""Small TEST-only publisher and clock for real Advisory/Account integration."""
from datetime import datetime,timedelta
from pathlib import Path
from copy import deepcopy
import json
from app.shell.bootstrap import build_application
from shared.config import Settings
from tests.support.provider import PlanProvider
from tests.support.facts import ClockedFacts
from tests.account_fixture import policy
ROOT=Path(__file__).resolve().parents[2]

class NativeFacts(ClockedFacts):
    native_facts_only=True
    mode='TEST'
    def health(self):return {'status':'CONNECTED'}
    def source_audit(self):return {'workspace_connected':True,'read_errors':[]}
    def snapshot(self):
        value=super().snapshot()
        for s in value['sessions']:
            member=self._session(s['tracking_session_id'])
            s['lifecycle']=member.get('lifecycle_status','ACTIVE')
            s['session_date']=member['session_date']
            s['source_event_max']=max([0]+[e['event_seq'] for e in self.events(s['tracking_session_id'])])
            s['source_observation_max']=s['last_observation_time']
            s['last_event_time']=max((x.get('timestamp','') for x in self.events(s['tracking_session_id'])),default=None)
        return value

    def advisory_facts(self,symbol):
        value=super().advisory_facts(symbol)
        for row in value['observations']:row.setdefault('source_format','V2A_OBSERVATIONS_EXPORT')
        extra=getattr(self,'snapshots',[])
        rows=[{**r['fields'],**{k:v for k,v in r.items() if k not in ('raw_payload','raw_payload_json','fields')},'timestamp':r['market_observed_at'],'exported_at':r['available_at'],'observation_kind':'SNAPSHOT'} for r in extra if r['symbol']==symbol]
        if rows:
            value['observations']+=rows;value['observations'].sort(key=lambda x:x['timestamp'])
            last=rows[-1];session=value['session']
            session.update(native_export=True,latest_snapshot_time=last['timestamp'],market_observed_at=last['timestamp'],last_observation_time=last['timestamp'],source_observation_max=last['timestamp'],price=last['price'],export_status={'state':'RUNNING','heartbeat_at':self.clock().isoformat()})
            value['current_state']=last
        return value

class NativeFixture:
    def __init__(self,root):
        self.root=root;self.workspace=root/'workspace';self.workspace.mkdir(parents=True,exist_ok=True)
        self.now=datetime.fromisoformat('2026-09-09T10:30:00+08:00');self.seq=1;self.price=10
        self.provider=PlanProvider();self.provider.action='HOLD'
        self.members={};self.native_events=[];self.native_observations=[]
        self.bridge=NativeFacts({'dataset_id':'TEST','source_session_date':self.now.date().isoformat(),'sessions':[],'facts':[]},lambda:self.now)
        self.add_symbol('bj920161','测试甲');self.add_symbol('sh688696','测试乙');self.publish()
        self.app=build_application(Settings(ROOT,data_root=root/'data',source='TEST',test_run_id='core'),live_bridge=self.bridge,advisory_provider=self.provider)
        self.p=self.app.portfolio;self.p.clock=lambda:self.now.isoformat()
        self.advisory=self.app.live_loop.advisory;self.advisory.clock=lambda:self.now;self.app.live_loop.interval=.05
    def add_symbol(self,symbol,name):
        identity=f'TS-{self.now:%Y%m%d}-{symbol}-01'
        self.members[symbol]={'tracking_session_id':identity,'symbol':symbol,'name':name,'session_date':self.now.date().isoformat(),'lifecycle_status':'ACTIVE'}
        return identity
    def publish(self):
        ds=self.bridge.dataset;ds['source_session_date']=self.now.date().isoformat();ds['sessions']=deepcopy(list(self.members.values()))
        ds['facts']=[{'kind':kind,'timestamp':x['timestamp'],'available_at':x.get('available_at',x['timestamp']),'symbol':x['symbol'],'tracking_session_id':x['tracking_session_id'],'payload':deepcopy(x)} for kind,rows in [('EVENT',self.native_events),('OBSERVATION',self.native_observations)] for x in rows]
    def append(self,symbol='bj920161',kind='NEW_HIGH',observation=True,event=True,price=10):
        self.now+=timedelta(seconds=10);member=self.members[symbol];identity=member['tracking_session_id']
        common={**member,'timestamp':self.now.isoformat(),'requested_time':self.now.strftime('%H:%M:%S'),'price':price}
        if observation:self.native_observations.append(common)
        if event:
            seq=1+max([0]+[x['event_seq'] for x in self.native_events if x['tracking_session_id']==identity])
            self.native_events.append({**common,'event_seq':seq,'type':kind,'label':kind,'severity':'IMPORTANT' if kind=='NEW_HIGH' else 'INFO','source':'tracker_5m'})
        self.publish()
    def create(self,mode='AUTO_SHADOW_EXECUTION'):
        account=self.p.create({'name':'隔离组合','idempotency_key':__import__('uuid').uuid4().hex,'account_type':'LIVE_SHADOW','initial_capital':200000,'policy':policy(ai_execution_mode=mode,max_position_weight_per_symbol=.9,max_total_exposure_pct=.95,max_new_exposure_per_day_pct=.95,minimum_cash_reserve_pct=0,slippage_model={'kind':'FIXED_BPS','bps':0})})
        self.p.bind({'account_id':account['account_id'],'binding_version':self.p.binding()['binding_version']})
        return account
    def close(self):
        self.app.live_loop.stop()
        if self.app.live_loop.thread:self.app.live_loop.thread.join(3)
        self.advisory._auto_pool.shutdown(wait=True)
        for router in self.app.routers:
            if hasattr(router,'close'):router.close()
