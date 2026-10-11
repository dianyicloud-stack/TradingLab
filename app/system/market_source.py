"""Fixed-source diagnostics and explicit Agent lifecycle. No cutover/fallback."""
from contextlib import contextmanager
from threading import RLock
import hashlib,json
from contracts.live.market_agent import AgentError
from .source_repository import now
class MarketSourceService:
    def __init__(self,repo,config,provider,lifecycle,quiescent):
        self.repo,self.config,self.provider,self.lifecycle,self.quiescent=repo,config,provider,lifecycle,quiescent
        self.lock=RLock();self.inflight=0
    @contextmanager
    def command_guard(self,path):
        if path.startswith('/api/system/'):
            yield;return
        with self.lock:self.inflight+=1
        try:yield
        finally:
            with self.lock:self.inflight-=1
    def status(self):
        data=self.repo.read();agent=self.lifecycle.status();identity=self.provider.identity()
        return {'active_market_source':'MARKET_AGENT','saved_market_source':'MARKET_AGENT',**identity,
            'live_source_owner':'MARKET_DATA_AGENT','observation_source_owner':'MARKET_DATA_AGENT',
            'configuration':self.config,'migration_required':data.get('migration_required',False),'agent':agent,
            'status':'RUNNING' if agent['status']=='RUNNING' else 'UNAVAILABLE',
            'message':'正式行情仅来自 Market Data Agent。' if agent['status']=='RUNNING' else 'Market Data Agent 不可用；检查数据目录、依赖和已批准的采集设置。不会使用其他行情源。',
            'ai_account_policy':'UNCHANGED','historical_operation_count':len(data['operations'])}
    def agent_control(self,action,payload):
        if payload.get('source')!=self.config['source'] or payload.get('schema_version')!='1.0' or payload.get('confirmation')!='CONFIRM_SOURCE_OPERATION' or not payload.get('command_id'):raise AgentError('SOURCE_COMMAND_CONTEXT_INVALID')
        digest=hashlib.sha256(json.dumps([action,payload],sort_keys=True).encode()).hexdigest()
        with self.lock,self.repo.lock:
            value=self.repo.migrate();key=payload['command_id'];old=value['operations'].get(key)
            if old:
                if old.get('request_sha256')!=digest:raise AgentError('COMMAND_ID_CONFLICT')
                if old.get('status')!='COMPLETED':raise AgentError('AGENT_COMMAND_RECONCILIATION_REQUIRED')
                return old['result']
            if self.inflight or not self.quiescent():raise AgentError('STOP_LISTENER_AND_WAIT_FOR_AI')
            if action=='start' and self.config['source']=='USER':
                from adapters.market_agent_process import validate_activation
                if not validate_activation(self.lifecycle.project,self.lifecycle.root)['enabled']:raise AgentError('MARKET_AGENT_ACTIVATION_REQUIRED')
            value['operations'][key]={'kind':'AGENT_LIFECYCLE','action':action,'request_sha256':digest,'status':'PENDING','at':now()};self.repo.write(value)
            try:
                result=self.lifecycle.start() if action=='start' else self.lifecycle.stop()
                if action=='start' and result.get('agent_state')!='RUNNING':result=self.lifecycle.collect()
                result={'status':result.get('agent_state',result.get('status')),'identity':result.get('agent_identity')}
                value['operations'][key].update(status='COMPLETED',result=result)
                value['config']['agent_auto_start']=action=='start';self.repo.write(value);return result
            except Exception as e:
                value['operations'][key].update(status='FAILED',error=getattr(e,'code',type(e).__name__));self.repo.write(value);raise
