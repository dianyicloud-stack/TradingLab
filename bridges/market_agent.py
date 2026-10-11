"""Only Agent Contract reads/commands; no market-owner repository connection."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import json,urllib.request,urllib.error,re
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from contracts.live.market_agent import AgentError
from contracts.live.bridge import BridgeError
from shared.logging.timing import stage

class AgentClient:
    def __init__(self,root,source='USER'):
        self.root=Path(root) if root else None;self.source=source
        self._read_scope=ContextVar('agent_read_scope',default=None)
    @contextmanager
    def snapshot_scope(self):
        if self._read_scope.get() is not None:
            yield
            return
        token=self._read_scope.set({})
        try:yield
        finally:self._read_scope.reset(token)
    def request(self,path,payload=None):
        if not self.root:raise AgentError('AGENT_NOT_CONFIGURED','后台数据服务尚未配置。',503)
        try:
            descriptor=json.loads((self.root/'connection.json').read_text(encoding='utf-8'))
            url=descriptor['url']
            if not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}',url):raise AgentError('AGENT_ENDPOINT_INVALID')
            request=urllib.request.Request(url+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Authorization':'Bearer '+descriptor['token'],'Content-Type':'application/json'})
            with stage('agent_ipc'):
                with urllib.request.urlopen(request,timeout=3 if payload is None else 95) as response:
                    with stage('agent_decode'):return json.load(response)
        except urllib.error.HTTPError as error:
            body=json.load(error);raise AgentError(body.get('error','AGENT_REQUEST_FAILED'),body.get('message'),error.code) from None
        except (OSError,ValueError,KeyError):raise AgentError('AGENT_UNAVAILABLE','后台数据服务未运行或连接信息不可读。',503) from None
    def query(self):
        scope=self._read_scope.get()
        if scope is not None and 'value' in scope:return deepcopy(scope['value'])
        value=self.request('/v1/state')
        if value.get('source')!=self.source:raise AgentError('AGENT_CONTEXT_MISMATCH')
        identity=value.get('agent_identity')
        if identity and Path(identity.get('root','')).resolve()!=self.root.resolve():raise AgentError('AGENT_INSTANCE_MISMATCH')
        if scope is not None:scope['value']=deepcopy(value)
        return value
    def command(self,payload):return self.request('/v1/commands',payload)
    def metadata(self,payload):return self.request('/v1/metadata',payload)

def project(value):
    """Map source facts only; market calculations remain the extracted native JS."""
    aliases={'price':'price','vwap':'vwap','alpha':'alpha','stockChange':'stock_pct','boardChange':'industry_pct','cumulativeVolume':'cumulative_volume','amount':'cumulative_amount','turnover':'cumulative_turnover','volumeRatio':'volume_ratio','boardMedianChange':'industry_breadth','deltaVolume':'delta_volume','deltaAmount':'delta_amount','deltaTurnover':'delta_turnover_pp','intervalVwap':'interval_vwap','vwapGap':'vwap_gap_pct','priceEfficiency':'price_efficiency','high':'high','low':'low','open':'open'}
    rows=[]
    for s in value['sessions']:
        identity=s['tracking_session_id'];observations=[];events=[]
        for fact in value['facts']:
            p=fact['payload']
            if p.get('tracking_session_id')!=identity:continue
            if fact['kind']=='EVENT':events.append(p);continue
            if fact['kind']=='OBSERVATION':
                raw=p['raw']
                def at(point):
                    if not point:return None
                    return s['date']+'T'+point+(':00' if len(point)==5 else '')+'+08:00'
                requested=at(raw['requestedTime'])
                market=at(raw.get('stockDataTime'))
                # A late manual fetch of the close is not a new market observation.
                # Scheduled observations keep their native interval; raw facts stay immutable.
                stamp=market if raw.get('source')!='auto' and market else requested
                observations.append({**{dst:raw.get(src) for src,dst in aliases.items()},'observation_id':fact['identity'],'record_id':fact['identity']+':'+str(fact['revision']),
                    'revision':fact['revision'],'symbol':s['symbol'],'tracking_session_id':identity,'session_date':s['date'],
                    'timestamp':stamp,'market_observed_at':market or stamp,'requested_at':requested,
                    'market_time_quality':'SOURCE_RECORDED' if market else 'SCHEDULE_ONLY',
                    'interval_end':at(raw.get('intervalEnd') or raw['requestedTime']),'interval_start':at(raw['intervalStart']),
                    'board_id':raw.get('boardCode') or None,'board_name':raw.get('boardName') or None,
                    'amount_trusted':raw.get('amountTrusted'),'quality_reason':raw.get('vwapIssue'),
                    'interval_complete':raw.get('source')=='auto','observation_kind':'FORMAL' if raw.get('source')=='auto' else 'IMMEDIATE',
                    'available_at':max(datetime.fromisoformat(raw['capturedAt'].replace(' ','T')+'+08:00'),datetime.fromisoformat(fact['recorded_at'])).isoformat(),'exported_at':fact['recorded_at'],
                    'quality':raw.get('quality'),'quality_version':raw.get('quality_version'),
                    'native_rule_evidence':{k:raw.get(k) for k in ('requestedTime','auctionPoint','price','high','low','intervalChange','volumeRatio','volumeRatioSample','cumulativeVolume','deltaVolume','vwap','vwapGap','amountTrusted','alpha','stockChange','boardChange','boardPending','priceEfficiency','deltaTurnover','comparisonTime','boardMedianChange','boardMedianTotal')},
                    'source_format':'V2A_NATIVE_EXPORT_V1','source_owner':'MARKET_DATA_AGENT','native_sha256':fact['sha256']})
            if fact['kind']=='SNAPSHOT':
                raw=p['sample'];stamp=raw.get('source_updated_at');fields={};times={}
                for key in ('price','open','high','low','stock_pct','cumulative_volume','cumulative_amount','cumulative_turnover','vwap','price_vwap_pct'):
                    at=raw.get('trade_source_captured_at') if key in ('cumulative_volume','cumulative_amount','cumulative_turnover','vwap','price_vwap_pct') else stamp
                    fields[key]=raw.get(key) if at else None;times[key]={'as_of':at}
                observations.append({**fields,'fields':fields,'field_times':times,'sample_id':fact['identity'],'record_id':fact['identity']+':'+fact['sha256'][:16],
                    'native_sha256':fact['sha256'],'timestamp':stamp,'market_observed_at':stamp,'available_at':raw['timestamp'],
                    'sampled_at':raw['timestamp'],'tracking_session_id':identity,'symbol':s['symbol'],'session_date':s['date'],
                    'source_format':'V2A_RUNTIME_SNAPSHOT_V1','source_owner':'MARKET_DATA_AGENT','publisher_id':'MARKET_DATA_AGENT',
                    'delivery':'LIVE','exported_at':fact['recorded_at']})
        observations.sort(key=lambda o:o['timestamp']);events.sort(key=lambda e:e['event_seq']);last=observations[-1] if observations else {}
        structured=[o for o in observations if o.get('observation_id')];snapshots=[o for o in observations if o.get('sample_id')]
        session={'tracking_session_id':identity,'symbol':s['symbol'],'name':s.get('stockName') or s['symbol'],'session_date':s['date'],'market_date':s['date'],'lifecycle':s.get('lifecycle_status','ACTIVE'),
            'last_observation_time':last.get('timestamp'),'market_observed_at':last.get('timestamp'),'price':last.get('price'),'price_time':last.get('timestamp'),
            'last_event_time':events[-1]['timestamp'] if events else None,'event_count':len(events),'source_event_max':events[-1]['event_seq'] if events else 0,
            'source_observation_max':last.get('timestamp'),'observation_status':'AVAILABLE' if observations else 'NOT_EXPORTED',
            'latest_snapshot_time':snapshots[-1]['timestamp'] if snapshots else None,'latest_structure_time':structured[-1]['timestamp'] if structured else None,
            'native_event_stream':True,'source_errors':value.get('errors',[]),'native_export':True,
            'export_status':{'state':'WATCHING' if value['agent_state']=='RUNNING' else 'STOPPED','quick_sample_task':value['agent_state'],'heartbeat_at':value.get('last_cycle_at')},
            'latest_complete_observation_time':next((x['timestamp'] for x in reversed(structured) if x['interval_complete']),None)}
        owned=[f for f in value['facts'] if f['payload'].get('tracking_session_id')==identity and f['kind'] in ('EVENT','OBSERVATION','SNAPSHOT')]
        data_identity=value.get('data_identity') or value.get('agent_identity',{}).get('root')
        versioned=[f for f in owned if isinstance(f.get('seq'),int)]
        session['source_watermark']={'identity':str(data_identity)+'|'+identity,'version':max([0]+[f['seq'] for f in owned])} if data_identity and len(versioned)==len(owned) else None
        session['source_commits']=[{'version':f['seq'],'at':f['recorded_at']} for f in sorted(versioned,key=lambda f:f['seq'])]
        session['source_owner']='MARKET_DATA_AGENT'
        rows.append({'session':session,'events':events,'observations':observations,'current_state':last})
    return rows

class AgentFactBridge:
    native_facts_only=True;workspace=None
    def __init__(self,client):self.client=client;self._projected=ContextVar('agent_projected',default=None)
    @contextmanager
    def snapshot_scope(self):
        if self._projected.get() is not None:
            yield
            return
        token=self._projected.set({})
        try:
            with self.client.snapshot_scope() if hasattr(self.client,'snapshot_scope') else nullcontext():yield
        finally:self._projected.reset(token)
    def fact_snapshot(self):
        try:
            cache=self._projected.get()
            if cache is not None and 'rows' in cache:return deepcopy(cache['rows'])
            with stage('agent_projection'):rows=project({**self.client.query(),'data_identity':(str(self.client.root.resolve())+'|'+getattr(self,'data_generation','OWNER')) if self.client.root else None})
            if cache is not None:cache['rows']=deepcopy(rows)
            return rows
        except AgentError as error:raise BridgeError(error.code,str(error),status=error.status) from None
    def sessions(self):return [r['session'] for r in self.fact_snapshot()]
    def advisory_facts(self,symbol):
        rows=[r for r in self.fact_snapshot() if r['session']['symbol']==symbol]
        if not rows:raise BridgeError('LIVE_SYMBOL_NOT_FOUND',status=404)
        return max(rows,key=lambda r:(r['session']['session_date'],r['session']['tracking_session_id']))
    def observations(self,identity):return next((r['observations'] for r in self.fact_snapshot() if r['session']['tracking_session_id']==identity),[])
    def events(self,identity):return next((r['events'] for r in self.fact_snapshot() if r['session']['tracking_session_id']==identity),[])
    def latest_observation(self,identity):return next(iter(reversed(self.observations(identity))),{})
    def connected(self):
        try:self.client.query();return True
        except AgentError:return False
    def health(self):return {'status':'CONNECTED' if self.connected() else 'NOT_CONNECTED','kind':'MARKET_DATA_AGENT'}
    def snapshot(self):return {'status':'CONNECTED','connection':self.health(),'sessions':self.sessions()}
    def source_audit(self):
        v=self.client.query();return {'workspace_connected':True,'files':[],'runtime_stock_count':len(v['sessions']),'runtime_updated_at':v.get('last_cycle_at'),'sampling_state':v['agent_state'],'read_errors':v['errors'],'native_export':{'status':{'state':v['agent_state'],'heartbeat_at':v.get('last_cycle_at'),'quick_sample_task':v['agent_state']},'errors':v['errors']},'sampling_evidence':'AGENT_OWNER_COMMIT'}
    def workspace_status(self):return {'path':str(self.client.root),'binding':'BOUND' if self.connected() else 'NOT_BOUND','readability':'READABLE' if self.connected() else 'ERROR','updated_at':None,'error_code':None}
