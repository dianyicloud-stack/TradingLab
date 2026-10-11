"""Explicit live read/review/watcher endpoints, no arbitrary workspace paths."""
from pathlib import Path
import hashlib
import re
from copy import deepcopy
from contextlib import nullcontext
from contracts.live.bridge import BridgeError
from shared.logging.timing import measured_lock, stage


class LiveRouter:
    def __init__(self, loop):
        self.loop = loop
        self.read_model=None
        code=Path(__file__).with_name('static').joinpath('live.js').read_bytes()
        root=Path(__file__).resolve().parents[2]
        paths=('app/live/router.py','engines/live/advisory.py','engines/live/advisory_repository.py',
               'engines/live/loop.py','app/system/runtime_state.py','app/system/runtime_control.py','app/system/runtime_web.py',
               'adapters/runtime_platform.py','adapters/runtime_windows.py','app/system/static/runtime-center.js',
               'engines/live/qualification.py','engines/live/synchronization.py','engines/live/analysis_status.py',
               'bridges/market_agent.py','bridges/active_market_source.py','adapters/source_configuration.py',
               'app/system/source_repository.py','app/system/market_source.py','app/shell/bootstrap.py','app/shell/server.py',
               'engines/live/evidence.py','engines/live/provider_request_repository.py',
               'adapters/ai/capabilities.py','adapters/ai/verification.py','app/system/ai_configuration.py','app/system/static/ai-settings.js','trading_lab.py',
               'adapters/ai/transport.py','adapters/ai/worker.py','adapters/ai/request_guard.py','adapters/ai/advisory.py','adapters/ai/config.py',
               'adapters/ai/providers/deepseek_provider.py','adapters/ai/providers/openai_provider.py','adapters/ai/providers/base.py','config/ai.yaml',
               'engines/live/native_health.py','engines/live/reading.py','engines/live/read_model.py','engines/live/triggers.py',
               'app/system/maintenance.py','app/system/artifact_retention.py','engines/live/retention.py','contracts/maintenance.py','shared/storage/maintenance.py','app/account/portfolio.py',
               'app/system/notifications.py','adapters/telegram.py','contracts/live/notification.py',
               'app/live/observation.py','app/live/static/data-observation.js','app/system/module.py',
               'app/live/history.py','app/live/static/history.js','app/live/static/reading-format.js','contracts/live/presentation.py',
               'app/live/templates/live.html','app/live/view.py','engines/history/bars.py','engines/history/store.py','engines/history/service.py','adapters/history_bars.py','contracts/history/bars.py')
        self.build_files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
        self.build_id=hashlib.sha256(code+''.join(self.build_files.values()).encode()).hexdigest()[:16]
        self.live_js=code.replace(b'__LIVE_BUILD_ID__',self.build_id.encode())

    def accepts_post(self, path):
        if re.fullmatch(r'/api/live/[A-Za-z0-9._-]{1,32}/(?:analyze|read)',path):return True
        return path in ('/api/live/listener/start','/api/live/listener/stop') or bool(re.fullmatch(r'/api/live/[A-Za-z0-9._-]{1,32}/advisory/analyze',path))

    def accepts_put(self,path):
        return path=='/api/live/advisory/settings' or bool(re.fullmatch(r'/api/live/[A-Za-z0-9._-]{1,32}/preferences',path))

    def route(self, method, path, payload=None):
        # Dispatch before acquiring a market-source consistency lock. Shell,
        # Observation and assets must not queue behind an aggregate collection.
        if not path.startswith('/api/live/'):
            return self._route_direct(method,path,payload) if path in ('/assets/live.js','/assets/live.css','/assets/display-refresh.js') else None
        provider = self.loop.workspace
        saved_view=re.fullmatch(r'/api/live/([A-Za-z0-9._-]{1,32})/advisory/(history|timeline)',path)
        if method=='GET' and saved_view and self.read_model:
            symbol,kind=saved_view.groups()
            requested=(payload or {}).get('tracking_session_id')
            if requested and self.loop.advisory.history_expired(requested):
                return 200,{'opinions' if kind=='history' else 'timeline':[],'availability':'RETENTION_EXPIRED','message':'已按保留策略清理；此日期不再提供完整回放。'},None
            cached=self.read_model.read()
            member=next((c['session'] for c in cached.get('advisory_cards',[])
                         if c['session']['symbol'].lower()==symbol.lower()),None)
            if not member:
                return 200,{'opinions' if kind=='history' else 'timeline':[],
                            'availability':'WAITING_CURRENT_SESSION','message':'当前跟踪信息尚未就绪，请稍后重试。'},None
            requested=(payload or {}).get('tracking_session_id')
            if requested and requested!=member['tracking_session_id']:
                return 200,{'opinions' if kind=='history' else 'timeline':[],
                            'availability':'SESSION_CHANGED','message':'跟踪已更新，请刷新当前股票后查看。'},None
            try:limit=max(1,min(int((payload or {}).get('limit',50 if kind=='history' else 100)),200))
            except (ValueError,TypeError):return 400,{'error':'INVALID_LIMIT','message':'历史条数无效。'},None
            operation=self.loop.advisory.history if kind=='history' else self.loop.advisory.timeline
            if 'limit' in (payload or {}):
                try:page=self.loop.advisory.opinions.history_page(symbol,member['tracking_session_id'],limit,(payload or {}).get('before'),(payload or {}).get('anchor'))
                except (ValueError,TypeError):return 400,{'error':'INVALID_PAGE','message':'历史页码无效。'},None
                if kind=='timeline':
                    page['timeline']=[{'advisory_id':x['advisory_id'],'generated_at':x['generated_at'],'action':x['action'],'dominant_side':x['dominant_side'],
                       'dominance_score':x['dominance_score'],'dominance_trend':x['dominance_trend'],'previous_hypothesis_review':x['previous_hypothesis_review']['status'],
                       'summary':x.get('current_state')} for x in reversed(page.pop('opinions'))]
                return 200,{**page,'tracking_session_id':member['tracking_session_id'],'availability':'READY'},None
            rows=operation(symbol,limit,session_identity=member['tracking_session_id'])
            return 200,{'opinions' if kind=='history' else 'timeline':rows,
                        'tracking_session_id':member['tracking_session_id'],'availability':'READY'},None
        if method=='GET' and path in ('/api/live/advisory/settings','/api/live/runtime-version','/api/live/mode'):
            result=self._route_direct(method,path,payload)
            return (result[0],{**result[1],**provider.identity()},result[2]) if hasattr(provider,'identity') else result
        if method=='GET' and path=='/api/live/view-context':
            cached=self.read_model.read() if self.read_model else {}
            identity=provider.identity() if hasattr(provider,'identity') else {}
            return 200,{'source':self.loop.source,**identity,'sessions':[c['session']['tracking_session_id'] for c in cached.get('advisory_cards',[])]},None
        if method=='GET' and path=='/api/live/stocks' and self.read_model:
            value=self.read_model.read()
            retired=self.loop.advisory.runtime.retired_sessions()
            if retired:
                value['advisory_cards']=[c for c in value.get('advisory_cards',[]) if c['session']['tracking_session_id'] not in retired]
                value['sessions']=[s for s in value.get('sessions',[]) if s.get('tracking_session_id') not in retired]
            if hasattr(provider,'identity') and any(value.get(k)!=v for k,v in provider.identity().items()):
                return 200,{'status':'INITIAL_LOADING','message':'正在读取当前行情服务；旧数据身份的缓存不再显示。',**provider.identity()},None
            return 200,self._display(value,payload),None
        with measured_lock(provider.lock) if method=='GET' and hasattr(provider,'identity') else nullcontext():
            result=self._route_direct(method,path,payload)
            if result and isinstance(result[1],dict) and hasattr(provider,'identity'):
                return result[0],{**result[1],**provider.identity()},result[2]
            if method=='GET' and path=='/api/live/stocks' and result:
                return result[0],self._display(result[1],payload),result[2]
            return result

    @staticmethod
    def _display(value,query):
        if (query or {}).get('view')!='display':return value
        value=deepcopy(value)
        known=set((query.get('opinions') or '').split(','))
        for card in value.get('advisory_cards',[]):
            opinion=card.get('latest')
            if opinion:
                if opinion.get('advisory_id') in known:
                    card['latest_unchanged_id']=opinion['advisory_id'];card.pop('latest')
                else:
                    for field in ('trigger_events','live_triggers','source_field_times'):opinion.pop(field,None)
            card['events']=[{k:v for k,v in event.items() if k in ('event_id','event_seq','tracking_session_id','symbol','stock_name','event_time','timestamp','summary','label','event_type','type','price','severity','level','source','observation_time')} for event in card.get('events',[])]
        return value

    def start_read_model(self,path):
        from engines.live.read_model import LiveReadModel
        def collect():
            provider=self.loop.workspace
            with provider.read_scope() if hasattr(provider,'read_scope') else provider.lock if hasattr(provider,'identity') else nullcontext():
                status,value,_=self._route_direct('GET','/api/live/stocks')
                if hasattr(provider,'identity'):value.update(provider.identity())
            if status!=200:raise ValueError(value.get('message') or value.get('error') or 'Live read model unavailable')
            return value
        self.read_model=LiveReadModel(path,collect);self.read_model.start()

    def close(self):
        if self.read_model:self.read_model.close()

    def _route_direct(self, method, path, payload=None):
        if method=='GET' and path=='/assets/display-refresh.js':
            return 200,Path(__file__).with_name('static').joinpath('display-refresh.js').read_bytes(),'text/javascript; charset=utf-8'
        if method == 'GET' and path == '/assets/live.js':
            return 200,self.live_js,'text/javascript; charset=utf-8'
        if method == 'GET' and path == '/assets/live.css':
            return 200,Path(__file__).with_name('static').joinpath('live.css').read_bytes(),'text/css; charset=utf-8'
        if not path.startswith('/api/live/'):
            return None
        try:
            if method=='GET' and path=='/api/live/runtime-version':
                return 200,{'release':'M2.2.3.4','build_id':self.build_id,'modules':self.build_files},None
            if method=='GET' and path=='/api/live/stocks':
                try:cards=self.loop.advisory.stock_cards();fact_error=None
                except BridgeError as error:cards=[];fact_error={'code':error.code,'message':str(error)}
                sync=self.loop.ingestion_health(cards)
                if fact_error:sync.update(listener_state='SOURCE_ERROR',error=fact_error['code'])
                return 200,{'schema_version':'1.2','status':'READY','mode':'REAL','source':self.loop.source,
                    'connection':sync['connection'],'listener_state':sync['listener_state'],'source_status':sync,'fact_error':fact_error,
                    'listener_error':self.loop.last_error,'advisory_cards':cards,
                    'advisory_settings':self.loop.advisory.catalog(),
                    'active_sessions':sum(c['session']['lifecycle'] in ('ACTIVE','TRACKED') for c in cards),
                    'ai_running':sum(c['health']['ai']['state']=='RUNNING' for c in cards),
                    'ai_queued':sum(c['health']['ai'].get('queued_requests',0)+bool(self.loop.advisory.runtime.pending(c['session']['tracking_session_id'])) for c in cards)},None
            stock=re.fullmatch(r'/api/live/([A-Za-z0-9._-]{1,32})/(preferences|analyze|read|events|observations/latest|status)',path)
            if stock:
                symbol,action=stock.groups();service=self.loop.advisory
                if method=='POST' and action=='read':return 200,service.mark_read(symbol,payload or {}),None
                if method=='PUT' and action=='preferences':return 200,service.preferences(symbol,payload or {}),None
                if method=='POST' and action=='analyze':
                    mode=(payload or {}).get('mode','NORMAL')
                    if set(payload or {})-{'mode'} or mode not in ('NORMAL','FORCE_REANALYSIS'):raise BridgeError('INVALID_ADVISORY_REQUEST',status=400)
                    try:return 201,service.analyze(symbol,force=mode=='FORCE_REANALYSIS'),None
                    except BridgeError as error:
                        if error.code in ('NO_NEW_ADVISORY_DATA','STALE_SOURCE_CONFIRM_REQUIRED'):
                            return 200,{'status':'NO_NEW_DATA' if error.code=='NO_NEW_ADVISORY_DATA' else error.code,
                                'message':'自上次AI分析后没有新的市场数据。' if error.code=='NO_NEW_ADVISORY_DATA' else str(error)},None
                        raise
                if method=='GET':
                    facts=self.loop.workspace.advisory_facts(symbol)
                    if action=='events':return 200,{'events':facts['events']},None
                    if action=='observations/latest':return 200,{'observation':facts['observations'][-1] if facts['observations'] else None},None
                    if action=='status':return 200,service.symbol_health(symbol),None
            if method == 'GET' and path == '/api/live/state':
                return 200,self.loop.snapshot(),None
            if method == 'GET' and path == '/api/live/mode':
                return 200,{'mode':'REAL','listener_state':self.loop.status,'supported_modes':['REAL']},None
            if method == 'GET' and path == '/api/live/advisory/settings':
                with stage('settings_catalog'):value=self.loop.advisory.catalog()
                return 200,value,None
            if method=='GET' and path=='/api/live/health' and self.loop.advisory:
                rows=[]
                for session in self.loop.workspace.sessions():
                    if session.get('symbol'):rows.append(self.loop.advisory.symbol_health(session['symbol']))
                return 200,{'schema_version':'1.1','watcher':self.loop.status,'symbols':rows},None
            advisory=re.fullmatch(r'/api/live/([A-Za-z0-9._-]{1,32})/advisory/(latest|history|timeline|analyze)',path)
            if advisory and self.loop.advisory:
                symbol,action=advisory.groups()
                if method=='GET' and action=='latest':return 200,{'opinion':self.loop.advisory.latest(symbol)},None
                if method=='GET' and action=='history':return 200,{'opinions':self.loop.advisory.history(symbol,(payload or {}).get('limit',50))},None
                if method=='GET' and action=='timeline':return 200,{'timeline':self.loop.advisory.timeline(symbol,(payload or {}).get('limit',100))},None
                if method=='POST' and action=='analyze':return 201,self.loop.advisory.analyze(symbol,trigger_type='MANUAL',force=(payload or {}).get('force',False)),None
            if method == 'PUT' and path == '/api/live/advisory/settings' and self.loop.advisory:
                return 200,self.loop.advisory.save_settings(payload),None
            if method == 'GET' and path == '/api/live/sessions':
                return 200,{'schema_version':'1.0','sessions':self.loop.workspace.sessions()},None
            match = re.fullmatch(r'/api/live/sessions/([A-Za-z0-9_-]{1,100})(?:/(observation|events))?',path)
            if method == 'GET' and match:
                identity,part = match.groups()
                operation = self.loop.workspace.events if part=='events' else self.loop.workspace.latest_observation if part=='observation' else self.loop.workspace.session_detail
                return 200,{'schema_version':'1.0','data':operation(identity)},None
            if method=='POST' and path in ('/api/live/listener/start','/api/live/listener/stop'):
                if payload:raise BridgeError('INVALID_REQUEST','此操作不接受额外字段。',400)
                return 200,self.loop.start() if path.endswith('/start') else self.loop.stop(),None
            return 404,{'error':'LIVE_ENDPOINT_NOT_FOUND','message':'Live接口不存在，请检查服务版本与页面是否一致。','path':path},None
        except BridgeError as error:
            body={'error':error.code,'message':str(error)}
            failure=getattr(error,'failure_metadata',None)
            if isinstance(failure,dict):
                body['failure']={key:failure[key] for key in ('task_id','stage','error_code','http_status','retryable',
                    'provider_attempt_count','transport_exception_type','reason','upstream_error') if key in failure}
            return error.http_status,body,None
