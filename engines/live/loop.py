"""Market Agent ingestion and per-symbol Advisory scheduling."""
from threading import Event,Lock,RLock,Thread
from contracts.live.bridge import BridgeError
from contracts.system import HealthCheck

class LiveLoop:
    def __init__(self,workspace,*,source='USER',interval=5,advisory=None):
        self.workspace,self.source,self.advisory=workspace,source,advisory
        self.interval=max(1,float(interval))
        self.stop_event,self.poll_lock,self.lifecycle_lock=Event(),Lock(),RLock()
        self.thread,self.status,self.last_error=None,'STOPPED',None
        self.intent=None;self.wait_reason='USER_STOPPED';self.last_progress=None

    def runtime_status(self):
        desired=self.intent.read() if self.intent else {'listener':'ENABLED' if self.thread and self.thread.is_alive() else 'DISABLED','revision':0}
        return {'desired':desired['listener'],'revision':desired['revision'],'actual':self.status,
            'reason':self.wait_reason,'error':self.last_error,'last_progress':self.last_progress,
            'loop_alive':bool(self.thread and self.thread.is_alive()),'migration':desired.get('migration')}

    def reconcile(self):
        if not self.intent:return
        with self.lifecycle_lock:
            desired=self.intent.read()
            if desired['listener']=='ENABLED':
                if not self.thread or not self.thread.is_alive():self.start(persist=False)
            elif self.thread and self.thread.is_alive():self.stop(persist=False)

    def ingestion_health(self,cards):
        """User-facing ingestion health, separate from formal worker lifecycle."""
        try:
            audit=self.workspace.source_audit()
            connected=audit['workspace_connected']
            available=[c for c in cards if c['events'] or c['session'].get('last_observation_time')]
            state='STOPPED' if self.status=='STOPPED' else 'RUNNING_NO_SOURCE' if not connected or not available else 'RUNNING_SYNCED'
            if state=='RUNNING_SYNCED':
                if any(c['sync']['status'] in ('SOURCE_IDENTITY_MISMATCH','SOURCE_VERSION_REGRESSED','CLOCK_SKEW','SOURCE_ERROR') for c in available):state='SOURCE_ERROR'
                elif all(c['health']['v2a']['status'] in ('STALE','UNKNOWN') for c in available):state='SOURCE_STALE'
                elif any(c['sync']['status']=='LAGGING' for c in available):state='RUNNING_LAGGING'
                elif any(c['sync']['status'] in ('PENDING','NOT_SYNCED','UNKNOWN') for c in available):state='RUNNING_PENDING'
            if not connected or audit.get('native_export',{}).get('errors'):state='SOURCE_ERROR'
            if any(e.get('code')!='INCOMPLETE_TAIL' for e in audit.get('read_errors',[])):state='SOURCE_ERROR'
            sample_states={c['health'].get('market',{}).get('quick_sample_task','UNKNOWN') for c in cards}
            return {**audit,'listener_state':state,'connection':{'status':'CONNECTED' if connected else 'NOT_CONNECTED'},
                'sampling_state':'RUNNING' if 'RUNNING' in sample_states else 'STOPPED' if sample_states=={'STOPPED'} else 'UNKNOWN',
                'last_event_time':max((c['session'].get('last_event_time') or '' for c in cards),default='') or None,
                'last_observation_time':max((c['session'].get('last_observation_time') or '' for c in cards),default='') or None,
                'last_read_at':max((c['sync'].get('read_at') or '' for c in cards),default='') or None,
                'sync_details':[{'symbol':c['session']['symbol'],**{k:c['sync'].get(k) for k in ('status','source_watermark','applied_watermark','lag_seconds','pending_since','grace_seconds')}} for c in cards]}
        except (BridgeError,OSError) as error:
            return {'listener_state':'SOURCE_ERROR','sampling_state':'UNKNOWN','connection':{'status':'ERROR'},
                'error':getattr(error,'code','WORKSPACE_READ_ERROR')}

    def poll(self,*,allow_analysis=True,wait_ai=True):
        if not self.poll_lock.acquire(blocking=False):return
        try:
            if not self.workspace.connected():
                self.last_error,self.status='MARKET_AGENT_NOT_CONNECTED','DEGRADED';self.wait_reason='SOURCE_CONNECTION_ERROR';return
            if self.advisory:
                self.advisory.ingest()
                if allow_analysis:self.advisory.poll_auto(wait=wait_ai)
            self.last_error=None
            if self.status!='STOPPED':self.status='WATCHING'
            if self.advisory:
                from engines.live.native_health import health
                phase=health({},self.advisory.clock(),self.advisory.market_is_open)['market_phase']
                self.wait_reason=phase if phase!='TRADING' else 'WAITING_ELIGIBLE_EVENT'
                summary=getattr(self.advisory,'ingestion_summary',{})
                if phase=='TRADING' and not summary.get('with_data'):self.wait_reason='WAITING_FIRST_DATA'
                if getattr(self.advisory,'source_errors',{}) and not summary.get('with_data'):
                    self.wait_reason='SOURCE_DATA_ERROR';self.last_error='PER_SYMBOL_SOURCE_ERROR'
                self.last_progress=self.advisory._stamp()
        except Exception as error:
            self.last_error,self.status=getattr(error,'code','LISTENER_ERROR'),'ERROR'
            self.wait_reason='SOURCE_OR_LISTENER_ERROR'
        finally:self.poll_lock.release()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.poll(wait_ai=False)
                self.stop_event.wait(self.interval)
        finally:self.status='STOPPED'

    def start(self,*,persist=True):
        with self.lifecycle_lock:
            if persist and self.intent:self.intent.update({'listener':'ENABLED'})
            if not persist and self.intent and self.intent.read()['listener']!='ENABLED':return self.runtime_status()
            if self.thread and self.thread.is_alive():return {'status':self.status}
            self.stop_event.clear();self.status='STARTING'
            self.thread=Thread(target=self._run,name='TradingLab-Live',daemon=True);self.thread.start()
            return {'status':self.status}

    def stop(self,*,persist=True):
        with self.lifecycle_lock:
            if persist and self.intent:self.intent.update({'listener':'DISABLED'})
            self.stop_event.set();self.wait_reason='USER_STOPPED' if persist else 'MAINTENANCE_PAUSED'
            return {'status':self.status,'stop_requested':True,'message':'停止接收新任务；运行中的分析安全完成后停止。'}

    def snapshot(self):
        cards=self.advisory.stock_cards() if self.advisory else []
        return {'schema_version':'1.0','source':self.source,'watcher':self.status,'listener_state':self.status,
                'listener_error':self.last_error,'advisory_cards':cards,'source_status':self.ingestion_health(cards)}

    def health(self):
        state=self.workspace.health()['status']
        return HealthCheck('live','Live','READY' if state=='CONNECTED' else state,'Market Data Agent → 独立AI意见 → 影子账户 / 通知')

    def health_checks(self):
        state=self.workspace.health()
        return [HealthCheck('market_agent_source','Market Data Agent',state['status'],state.get('error_code') or '唯一正式行情来源'),
                HealthCheck('fast_advisory','AI分析','READY' if self.advisory else 'ERROR','不可变意见、输入与独立成功水位'),
                HealthCheck('listener','实时监听',self.status,self.last_error or '按股票读取和分析')]
