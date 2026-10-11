"""M2.2.1 Fast Advisory domain service.

Owns frozen analysis windows and coordination. It never creates a Formal
Decision or writes the V2A confirmed cursor.
"""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib,json
from pathlib import Path
from threading import RLock,BoundedSemaphore
from concurrent.futures import ThreadPoolExecutor
import jsonschema

from contracts.live.bridge import BridgeError
from contracts.live.advisory import REASONING,AUTO_AI_MODES,ACTIONS,ACTION_ALIASES,action_definition
from shared.serialization import canonical
from shared.datetime import iso_utc,utc_now
from shared.ids import new_id
from engines.live.reading import fingerprint,model_key,portfolio_key,time_metadata,event_summary
from engines.live.triggers import RULES,detect
from engines.live.analysis_status import MESSAGES, failure_metadata, legacy_failure
from engines.live.analysis_diagnostics import AnalysisDiagnostics
from engines.live.qualification import NATIVE_EVENTS, VERSION as QUALITY_VERSION, validate as validate_event
from engines.live.synchronization import status as synchronization_status

_UNSET=object()

PROMPT='''1. Role / philosophy
你是 Trading Lab 的盘中博弈推演助手。只依据输入的冻结窗口判断供需、主动性与价格推动效率；不补充外部事实，不执行交易，不生成 Formal Decision、Review 或 ACK。Action 只是建议。

2. Frozen analysis window
incremental_evidence 是本轮相对 Advisory Cursor 的完整新增事实；analysis_windows 明确其边界。不得把 context_evidence 中的旧事实重新描述为本轮新增。

3. Previous advisory
先评价 previous_advisory 的主假设在新增证据下是 CONFIRMED、STRENGTHENED、WEAKENED、INVALIDATED、UNCHANGED 或 INSUFFICIENT_EVIDENCE。

4. Incremental evidence
优先解释 delta_since_previous、增量 Event 和增量 Observation。数值差由系统计算，禁止另行臆算。

5. Current market context
历史只用于理解新增变化。区分卖方有效压价与推动效率衰减后的吸收；VWAP 是动态成交成本与接受参考。只讨论可观察行为，不声称主力或机构的确定心理。

6. Portfolio context / ownership / recent actions
portfolio_context 来自统一 Account Engine，与市场事实分别冻结。先独立完成 Market View，不能因仓位限制篡改市场方向。
再给出独立 portfolio_plan：portfolio_action 为 NONE/OPEN/ADD/REDUCE/EXIT/HOLD，明确 target_weight（0–1）与 reason。
没有明确 sizing 时省略 target_weight，系统会标记 NEEDS_SIZING；禁止默认25%。账户未初始化或执行模式 OFF 时只给 NONE。
尊重 AI_MANAGED / MANUAL_PROTECTED 归属，AI 不能自动出售手工保护仓；账户异常时保留市场分析，暂停执行。
已有持仓时增加总目标仓位使用 ADD，不能再当成空仓 OPEN；不增加风险使用 HOLD。target_weight 是成交后的总目标，不是额外买入比例。
recent_account_actions 是实际账户操作审计（包括 MANUAL_OPEN/ADD/REDUCE/EXIT）；使用最新数量、成本、可卖、T+1与归属继续判断。
scenario_tree 是未来条件分支，不能视为已确认下单命令；portfolio_plan 只描述当前可执行计划。

6. Required reasoning tasks
依次回答上一判断变化、当前博弈、优势迁移、核心矛盾、转强/整理/转弱条件路径、下一观察重点与主假设失效条件。场景条件必须具体可验证。

7. Required output schema
严格输出符合 JSON Schema 的中文 JSON。Schema 字段名和枚举保持原样；用户可阅读的正文必须使用中文业务术语，不直接输出变量名、null、内部状态枚举。previous_advisory 为空仅表示首次分析、暂无上一轮意见可比较，不等于当前市场证据不足；证据质量必须独立判断。只列有事实依据的条件和价位，不机械凑多个场景。game_state 优先使用结构化对象；next_observation_focus 优先使用 target/watch_for/meaning 对象。Confidence 表示对当前结构判断的置信度，不是上涨概率、收益概率或胜率。'''

DEFAULT_IMPORTANT_EVENTS=('ALPHA_DETERIORATE','BREAKDOWN','BREAKOUT','STRUCTURE_INVALIDATED','RISK_ESCALATION')
METRICS=('price','vwap_gap','vwap_gap_pct','alpha','volume','delta_volume','delta_amount','delta_turnover','delta_turnover_pp','volume_ratio','price_efficiency')

def _value_time(row):
    if not isinstance(row,dict):return None
    return row.get('requested_time') or row.get('timestamp') or row.get('last_observation_time') or row.get('updated_at')

def _key(value):
    if not isinstance(value,str):return ''
    return value.split('T',1)[-1][:8]

def _latest(*values):
    rows=[x for x in values if isinstance(x,str) and x]
    return max(rows,key=_key) if rows else None

def _earliest(*values):
    rows=[x for x in values if isinstance(x,str) and x]
    return min(rows,key=_key) if rows else None

class AdvisoryService:
    def __init__(self,workspace,runtime,opinions,provider,*,source='USER',clock=utc_now,
                 ):
        self.workspace,self.runtime,self.opinions,self.provider=workspace,runtime,opinions,provider
        self.source,self.clock=source,clock
        self.runtime_mode='LIVE'
        self.model_configuration=None
        self.accepting=True
        self._locks_guard,self._locks=RLock(),{}
        self._auto_pool=ThreadPoolExecutor(max_workers=8,thread_name_prefix='TradingLab-LiveAI')
        self._auto_futures={}
        self._provider_slots=BoundedSemaphore(8)
        self.portfolio_context=lambda symbol:{'status':'NOT_INITIALIZED','ai_execution_mode':'ADVISORY_ONLY'}
        self.portfolio_result=lambda opinion,frozen:None
        self.success_observer=lambda event:None
        self.stock_metadata=lambda symbol:None
        self.market_is_open=lambda day:None
        self.listener_state=lambda:'WATCHING'
        self.listener_intent=lambda:{}
        self.diagnostics=AnalysisDiagnostics.configured()
        self.schema=json.loads((Path(__file__).resolve().parents[2]/'contracts/live/advisory_opinion_1.0.json').read_text(encoding='utf-8'))

    def _stamp(self):return iso_utc(self.clock())

    def active_work(self):
        with self._locks_guard:
            if any(not f.done() for f in self._auto_futures.values()):return True
        return self.runtime.active_requests()

    def notification_boundary(self):
        return self.runtime.notification_boundary()

    def notification_completions(self,after,limit=100):
        rows=self.runtime.notification_completions(after,limit)
        for row in rows:
            if row['status']=='COMPLETED' and row.get('opinion_id'):
                row['opinion']=self.opinions.by_id(row['opinion_id'])
        return rows
    def _symbol_lock(self,identity):
        with self._locks_guard:return self._locks.setdefault(identity,RLock())

    def catalog(self):
        # Registry availability is an AI concern, never a prerequisite for facts.
        try:
            catalog=self.provider.catalog()
            if not isinstance(catalog.get('providers'),list):raise ValueError('registry')
            registry_error=None
        except Exception:
            catalog={'providers':[],'default_provider':None,'default_model':None}
            registry_error='AI_CONFIGURATION_UNAVAILABLE'
        stored=self.runtime.settings();global_value=stored.get('GLOBAL',{})
        defaults={'provider':catalog.get('default_provider'),'model':catalog.get('default_model'),'reasoning_effort':'low',
                  'auto_ai_mode':'OFF','debounce_seconds':4.0,'fresh_seconds':90,'delayed_seconds':300,
                  'important_event_types':list(DEFAULT_IMPORTANT_EVENTS),'auto_event_max_age_seconds':900}
        global_setting={**defaults,**global_value}
        if self.model_configuration:global_setting.update(self.model_configuration.resolve())
        if 'auto_ai_mode' not in global_value and global_value.get('auto_ai') is not None:
            global_setting['auto_ai_mode']='ALL_EVENTS' if global_value['auto_ai'] else 'OFF'
        global_setting['auto_ai']=global_setting['auto_ai_mode']!='OFF'
        overrides={}
        for key,value in stored.items():
            if not key.startswith('SYMBOL:'):continue
            row=dict(value)
            if 'auto_ai_mode' not in row and row.get('auto_ai') is not None:row['auto_ai_mode']='ALL_EVENTS' if row['auto_ai'] else 'OFF'
            overrides[key[7:]]=row
        return {'schema_version':'1.1','catalog':catalog,'global':global_setting,'overrides':overrides,
                'provider_status':self._provider_state(catalog,global_setting,registry_error),
                'reasoning_efforts':list(REASONING),'auto_ai_modes':list(AUTO_AI_MODES),
                'actions':list(ACTIONS.values()),'freshness_thresholds':{'fresh_seconds':global_setting['fresh_seconds'],'delayed_seconds':global_setting['delayed_seconds']}}

    @staticmethod
    def _provider_state(catalog,settings,error=None):
        selected=next((p for p in catalog['providers'] if p['provider']==settings.get('provider') and settings.get('model') in p['models']),None)
        reason=error or ('AI_PROVIDER_NOT_CONFIGURED' if selected is None else selected.get('error'))
        if selected and 'model_capabilities' in selected:
            supported=selected['model_capabilities'].get(settings.get('model'),{}).get('reasoning_efforts',[])
            if settings.get('reasoning_effort') not in supported:reason=reason or 'MODEL_REASONING_UNSUPPORTED'
        return {'status':'ERROR' if reason else 'READY','reason':reason,
                'provider':settings.get('provider'),'model':settings.get('model')}

    def save_settings(self,payload):
        allowed={'scope','symbol','provider','model','reasoning_effort','auto_ai','auto_ai_mode','debounce_seconds',
                 'pin_order','fresh_seconds','delayed_seconds','important_event_types','auto_event_types','auto_event_max_age_seconds','follow_default'}
        if set(payload)-allowed:raise BridgeError('INVALID_ADVISORY_SETTINGS')
        symbol=payload.get('symbol')
        if symbol is not None and (not isinstance(symbol,str) or not symbol.strip()):raise BridgeError('INVALID_ADVISORY_SETTINGS')
        symbol=symbol.lower() if symbol else None;scope='SYMBOL:'+symbol if symbol else 'GLOBAL'
        value={k:v for k,v in payload.items() if k not in ('scope','symbol','follow_default')}
        follow=payload.get('follow_default',False)
        if type(follow) is not bool or follow and (not symbol or any(k in value for k in ('provider','model','reasoning_effort'))):raise BridgeError('INVALID_ADVISORY_SETTINGS')
        if 'auto_ai' in value:
            if type(value['auto_ai']) is not bool:raise BridgeError('INVALID_AUTO_AI')
            value['auto_ai_mode']='ALL_EVENTS' if value.pop('auto_ai') else 'OFF'
        current=self.catalog();providers=current['catalog']['providers'];provider=value.get('provider');model=value.get('model')
        if (provider is None)!=(model is None):raise BridgeError('INVALID_ADVISORY_MODEL')
        if provider is not None and not any(x['provider']==provider and model in x['models'] for x in providers):raise BridgeError('INVALID_ADVISORY_MODEL')
        if 'reasoning_effort' in value and value['reasoning_effort'] not in REASONING:raise BridgeError('INVALID_REASONING_EFFORT')
        if 'auto_ai_mode' in value and not (symbol and value['auto_ai_mode'] is None) and value['auto_ai_mode'] not in AUTO_AI_MODES:raise BridgeError('INVALID_AUTO_AI_MODE')
        if 'debounce_seconds' in value and (type(value['debounce_seconds']) not in (int,float) or not 3<=value['debounce_seconds']<=5):raise BridgeError('INVALID_DEBOUNCE')
        if 'pin_order' in value and value['pin_order'] is not None and (type(value['pin_order']) is not int or value['pin_order']<0):raise BridgeError('INVALID_PIN_ORDER')
        if any(k in value and (type(value[k]) is not int or value[k]<1) for k in ('fresh_seconds','delayed_seconds')):raise BridgeError('INVALID_FRESHNESS_THRESHOLD')
        effective={**current['global'],**current['overrides'].get(symbol,{})};check={**effective,**value}
        selected=next((p for p in providers if p['provider']==check['provider']),None)
        if selected and 'model_capabilities' in selected and check['reasoning_effort'] not in selected['model_capabilities'].get(check['model'],{}).get('reasoning_efforts',[]):
            raise BridgeError('MODEL_REASONING_UNSUPPORTED')
        if check['fresh_seconds']>=check['delayed_seconds']:raise BridgeError('INVALID_FRESHNESS_THRESHOLD')
        if 'important_event_types' in value and (not isinstance(value['important_event_types'],list) or not all(isinstance(x,str) and x for x in value['important_event_types'])):raise BridgeError('INVALID_IMPORTANT_EVENTS')
        if 'auto_event_types' in value and (not isinstance(value['auto_event_types'],list) or any(t not in NATIVE_EVENTS and t not in RULES for t in value['auto_event_types'])):raise BridgeError('INVALID_EVENT_TYPES')
        if 'auto_event_max_age_seconds' in value and (type(value['auto_event_max_age_seconds']) is not int or not 30<=value['auto_event_max_age_seconds']<=3600):raise BridgeError('INVALID_EVENT_AGE')
        stored=self.runtime.settings().get(scope,{})
        keys=('provider','model','reasoning_effort','auto_ai_mode','debounce_seconds','pin_order','fresh_seconds','delayed_seconds','important_event_types','auto_event_types','auto_event_max_age_seconds')
        merged={key:stored.get(key) for key in keys if stored.get(key) is not None};merged.update(value)
        if merged.get('auto_ai_mode') is None:merged.pop('auto_ai_mode',None);merged.pop('auto_ai',None)
        else:merged['auto_ai']=merged['auto_ai_mode']!='OFF'
        if symbol and 'auto_ai_mode' in value:
            preference=self.runtime.preferences(symbol)
            if 'auto_ai_mode' in preference:
                preference.pop('auto_ai_mode');self.runtime.save_preferences(symbol,preference)
        if any(k in value and stored.get(k)!=value[k] for k in ('auto_ai_mode','important_event_types','auto_event_types')):
            for target in ([symbol] if symbol else [f['session']['symbol'] for f in self.current_facts()]):self.establish_auto_boundary(target)
        if follow:
            for key in ('provider','model','reasoning_effort','max_output_tokens'):merged.pop(key,None)
        if self.model_configuration and not symbol:
            selection={k:v for k,v in value.items() if k in ('provider','model','reasoning_effort')}
            if selection:self.model_configuration.save(selection)
            for key in ('provider','model','reasoning_effort'):merged.pop(key,None)
        self.runtime.save_setting(scope,merged,self._stamp());return self.catalog()

    def effective(self,symbol):
        settings=self.catalog();override=settings['overrides'].get(symbol.lower(),{});value={**settings['global'],**override}
        if self.model_configuration:
            selection={k:v for k,v in override.items() if k in ('provider','model','reasoning_effort','max_output_tokens')}
            value.update(self.model_configuration.resolve(selection))
        value.update(self.runtime.preferences(symbol))
        value['auto_ai_mode']=value.get('auto_ai_mode') or ('ALL_EVENTS' if value.get('auto_ai') else 'OFF')
        value['provider_status']=self._provider_state(settings['catalog'],value,
            settings['provider_status']['reason'] if not settings['catalog']['providers'] else None)
        value['auto_ai']=value['auto_ai_mode']!='OFF'
        pref=self.runtime.preferences(symbol)
        value['model_configuration_origin']=value.get('configuration_origin')
        value['configuration_origin']={'mode':'STOCK' if 'auto_ai_mode' in pref or 'auto_ai_mode' in settings['overrides'].get(symbol.lower(),{}) else 'GLOBAL',
            'types':'STOCK' if 'auto_event_types' in pref or 'auto_event_types' in settings['overrides'].get(symbol.lower(),{}) else 'GLOBAL' if 'auto_event_types' in settings['global'] else 'DEFAULT_NATIVE_TYPES'}
        return value

    def preferences(self,symbol,payload):
        allowed={'visible','pinned','collapsed','auto_ai_mode','auto_event_types','live_trigger_config'}
        if set(payload)-allowed:raise BridgeError('INVALID_LIVE_PREFERENCES',status=400)
        if any(k in payload and type(payload[k]) is not bool for k in ('visible','pinned','collapsed')):raise BridgeError('INVALID_LIVE_PREFERENCES',status=400)
        if 'auto_ai_mode' in payload and payload['auto_ai_mode'] is not None and payload['auto_ai_mode'] not in AUTO_AI_MODES:raise BridgeError('INVALID_AUTO_AI_MODE',status=400)
        types=payload.get('auto_event_types')
        known={e.get('type') or e.get('event_type') for e in self._member(symbol)[0]['events']}
        known.update(RULES);known.update(NATIVE_EVENTS)
        if 'live_trigger_config' in payload:
            config=payload['live_trigger_config']
            if not isinstance(config,dict) or set(config)-{'threshold_percent','window_seconds','cooldown_seconds','max_sample_gap_seconds'} or any(type(v) not in (int,float) or not 0<v<=3600 for v in config.values()):
                raise BridgeError('INVALID_TRIGGER_CONFIG',status=400)
        # Unknown categories cannot silently become active triggers.
        if types is not None and (not isinstance(types,list) or any(not isinstance(t,str) or t not in known for t in types)):
            raise BridgeError('INVALID_EVENT_TYPES',status=400)
        before=self.runtime.preferences(symbol);after={**before,**payload}
        for key in ('auto_ai_mode','auto_event_types'):
            if key in payload and payload[key] is None:after.pop(key,None)
        if any(k in payload and before.get(k)!=after.get(k) for k in ('auto_ai_mode','auto_event_types','live_trigger_config')):self.establish_auto_boundary(symbol)
        self.runtime.save_preferences(symbol,after)
        return self.effective(symbol)

    def current_facts(self):
        symbols=sorted({s['symbol'] for s in self.workspace.sessions() if s.get('symbol')})
        facts=[];self.source_errors={}
        for symbol in symbols:
            try:facts.append(self.workspace.advisory_facts(symbol))
            except (BridgeError,OSError) as error:self.source_errors[symbol]=getattr(error,'code',type(error).__name__)
        facts=[f for f in facts if not self.runtime.retired(f['session']['tracking_session_id']) and not self.runtime.expired(f['session']['tracking_session_id'])]
        day=max((f['session'].get('market_date') or '' for f in facts),default='')
        return [f for f in facts if (f['session'].get('market_date') or '')==day]

    def ingest(self):
        current=self.current_facts();self.ingestion_summary={'sessions':len(current),'with_data':sum(bool(f.get('observations')) for f in current)}
        for facts in current:
            self.runtime.ingest(facts,self._stamp())
            detect(self.runtime,facts,self.effective(facts['session']['symbol']),self.clock())

    def mark_read(self,symbol,payload):
        identity=self._member(symbol)[1]['tracking_session_id']
        if set(payload)-{'tracking_session_id','advisory_id','event_seq'} or payload.get('tracking_session_id')!=identity:
            raise BridgeError('INVALID_READ_POSITION',status=400)
        opinion_id=payload.get('advisory_id');position=self.opinions.opinion_position(opinion_id,identity) if opinion_id else 0
        seq=payload.get('event_seq',0)
        if position is None or type(seq) is not int or not 0<=seq<=self._member(symbol)[1].get('source_event_max',0):
            raise BridgeError('INVALID_READ_POSITION',status=400)
        return self.runtime.mark_read(identity,position,seq)

    def stock_cards(self):
        cards=[]
        for facts in self.current_facts():
            s=facts['session'];symbol=s['symbol'];identity=s['tracking_session_id']
            if not s.get('name') or s['name']==symbol:s['name']=self._member(symbol)[1]['name']
            settings=self.effective(symbol);latest=self.latest(symbol);health=self.symbol_health(symbol,latest_opinion=latest)
            diagnostics={**self.runtime.ingestion(identity),
                'source_event_max':s.get('source_event_max',max([0]+[x['event_seq'] for x in facts['events']])),
                'source_observation_max':s.get('last_observation_time'),
                'advisory_cursor':self.runtime.cursor(identity)}
            event_cursor=diagnostics.get('listener_event_cursor',0)
            read_event=next((e for e in reversed(facts['events']) if e.get('event_seq',0)<=event_cursor),{})
            read_time=_latest(diagnostics.get('listener_observation_cursor'),_value_time(read_event))
            source_time=_latest(s.get('last_observation_time'),s.get('last_event_time'))
            def seconds(value):
                parts=(_key(value)+':00').split(':')[:3]
                return sum(int(p)*unit for p,unit in zip(parts,(3600,60,1)))
            lag=max(0,seconds(source_time)-seconds(read_time)) if source_time and read_time else None
            diagnostics.update(source_data_time=source_time,listener_data_time=read_time,
                               lag_seconds=lag,status='NOT_SYNCED' if lag is None else 'LAGGING' if lag else 'SYNCED')
            if s.get('source_errors') or diagnostics.get('errors'):diagnostics.update(status='SOURCE_ERROR',errors=s.get('source_errors') or diagnostics['errors'])
            exported=s.get('latest_exported_at');ingested=diagnostics.get('read_at')
            native_rows=[r for r in facts['observations'] if r.get('record_id')]
            if native_rows:ingested=self.runtime.ingested_at(identity,native_rows[-1]['record_id'])
            diagnostics['ingested_at']=ingested
            diagnostics['export_to_read_seconds']=None
            if exported and ingested:
                from engines.live.native_health import instant
                diagnostics['export_to_read_seconds']=max(0,(instant(ingested)-instant(exported)).total_seconds())
            events=[{**e,'event_time':e.get('timestamp') or e.get('event_time'),
                'event_type':e.get('type') or e.get('event_type'), 'summary':e.get('label') or e.get('summary'),
                'stock_name':e.get('name') or s.get('name'),'associated_observation_time':e.get('associated_observation_time') or e.get('requested_time') or e.get('timestamp'),'source':'V2A_NATIVE','native_source':e.get('source')} for e in facts['events']]
            types={**NATIVE_EVENTS,**{e['event_type']:e.get('label') or e['event_type'] for e in events if e['event_type']}}
            types.update(RULES)
            if s.get('source_owner')=='MARKET_DATA_AGENT':diagnostics.update(synchronization_status(s,self.runtime.ingestion(identity),self.clock()))
            read=self.runtime.native_control(identity,'READ_POSITION') or {}
            unread=[r['opinion'] for r in self.opinions.reading(symbol,identity,read.get('opinion_position',0)) if r['opinion'].get('effective_result',True)]
            cards.append({'session':s,'settings':settings,'health':health,'latest':latest,
                          'events':events,'event_types':types,'sync':diagnostics,'event_summary':event_summary(events,s.get('session_date')),
                          'unread':{'opinions':len(unread),'important_changes':sum(r.get('change_severity') in ('IMPORTANT','CRITICAL') for r in unread),
                              'events':sum(e['event_seq']>read.get('event_seq',0) for e in events)},
                          'live_triggers':self.runtime.native_control(identity,'LIVE_TRIGGERS') or []})
        def priority(c):
            opinion=c['latest'] or {};settings=c['settings'];events=c['events']
            important=any(self._important([e],settings) for e in events[-1:])
            return (not (settings.get('pinned') or settings.get('pin_order') is not None),
                    not important,not bool(opinion.get('delta_since_previous',{}).get('action',{}).get('changed')),
                    opinion.get('action') not in ('EXIT','REDUCE'),not bool(opinion),
                    -(c['session'].get('source_event_max') or 0),c['session']['symbol'])
        return sorted(cards,key=priority)

    def _member(self,symbol):
        facts=self.workspace.advisory_facts(symbol)
        member={**facts['session'],'session_date':facts['session'].get('market_date')}
        identity=member['tracking_session_id']
        if self.runtime.expired(identity):raise BridgeError('RETENTION_EXPIRED','已按保留策略清理；此日期不再提供完整回放或重新分析。',status=410)
        # A runtime quote file is overwritten by its owner. Retain observations
        # previously read by the listener so intermediate samples remain in the
        # next frozen incremental window, even after the source snapshot moves on.
        for key,kind in (('events','EVENT'),('observations','OBSERVATION')):
            retained=self.runtime.ingested_facts(identity,kind)
            if kind=='OBSERVATION' and getattr(self.workspace,'native_facts_only',False):
                # Preserve old audit bytes but do not misclassify a former formal
                # export cache as ongoing native sampling.
                retained=[r for r in retained if r.get('source_format') in ('V2A_OBSERVATIONS_EXPORT','V2A_RUNTIME_STATE','V2A_MARKET_RAW_CSV','V2A_NATIVE_EXPORT_V1','V2A_RUNTIME_SNAPSHOT_V1')]
            rows=retained+facts[key]
            unique={}
            for r in rows:
                record_key=str(r['event_seq']) if kind=='EVENT' else ('NATIVE_OBSERVATION' if r.get('observation_id') else r.get('source_format'),r.get('observation_id') or _key(_value_time(r)))
                if r.get('revision',0)>=unique.get(record_key,{}).get('revision',0):unique[record_key]=r
            facts[key]=sorted(unique.values(),key=lambda r:r['event_seq'] if kind=='EVENT' else _key(_value_time(r)))
        if not member.get('name') or member['name']==member['symbol']:
            metadata=self.stock_metadata(symbol) or {}
            member['name']=metadata.get('instrument_name') or member['symbol']
        return facts,member

    def _freshness(self,session_date,latest,settings):
        if not latest:return {'status':'UNKNOWN','latest_data_time':None,'delay_seconds':None}
        # Isolated HTTP fixtures have intentionally fixed historical dates.
        # Unit freshness tests inject their own clock and still exercise every
        # threshold; production always uses real elapsed time.
        if self.source=='TEST' and self.clock is utc_now:
            return {'status':'FRESH','latest_data_time':latest,'delay_seconds':0,'fresh_seconds':settings['fresh_seconds'],'delayed_seconds':settings['delayed_seconds']}
        # Isolated application fixtures use historical dates and the default
        # wall clock. Unit freshness scenarios inject their own clock.
        if self.source=='TEST' and self.clock is utc_now:
            return {'status':'FRESH','latest_data_time':latest,'delay_seconds':0,'fresh_seconds':settings['fresh_seconds'],'delayed_seconds':settings['delayed_seconds']}
        try:
            stamp=datetime.fromisoformat(latest.replace('Z','+00:00')) if 'T' in latest else datetime.fromisoformat(f'{session_date}T{latest}').replace(tzinfo=timezone(timedelta(hours=8)))
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone(timedelta(hours=8)))
            delay=max(0,int((self.clock().astimezone(timezone.utc)-stamp.astimezone(timezone.utc)).total_seconds()))
            status='FRESH' if delay<=settings['fresh_seconds'] else 'DELAYED' if delay<=settings['delayed_seconds'] else 'STALE'
            return {'status':status,'latest_data_time':latest,'delay_seconds':delay,'fresh_seconds':settings['fresh_seconds'],'delayed_seconds':settings['delayed_seconds']}
        except (ValueError,TypeError):return {'status':'UNKNOWN','latest_data_time':latest,'delay_seconds':None}

    @staticmethod
    def _metric_state(frozen):
        evidence=frozen.get('incremental_evidence') or {};context=frozen.get('context_evidence') or {}
        rows=evidence.get('observations') or context.get('observations') or []
        state={}
        for source in (rows[-1] if rows else {},frozen.get('current_state',{}),frozen.get('live_observation',{})):
            if isinstance(source,dict):state.update({k:v for k,v in source.items() if v is not None})
        return state

    @classmethod
    def _delta(cls,current,previous_input):
        before=cls._metric_state(previous_input or {});after=cls._metric_state(current);result={}
        for key in METRICS:
            old,new=before.get(key),after.get(key)
            if old is None and new is None:continue
            change=round(new-old,8) if isinstance(old,(int,float)) and isinstance(new,(int,float)) else None
            result[key]={'previous':old,'current':new,'change':change,
                         'direction':'UP' if change is not None and change>0 else 'DOWN' if change is not None and change<0 else 'STABLE' if change==0 else 'NEW'}
        return result

    def freeze(self,symbol,trigger_type,model_settings=None):
        source,member=self._member(symbol);identity=member['tracking_session_id'];session_date=member.get('session_date') or source.get('session_date')
        if self.runtime.retired(identity):raise BridgeError('TRACKING_DELETED','该跟踪已删除；重新添加后才能分析。',409)
        cursor=self.runtime.cursor(identity);last_seq=(cursor or {}).get('last_advised_event_seq',0);last_time=(cursor or {}).get('last_advised_observation_time')
        events=deepcopy(source['events']);observations=deepcopy(source['observations'])
        def analysis_sample(row):
            if row.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1':
                # The reader retains exact producer bytes for audit. Untimed
                # cache values inside those bytes are not analysis evidence.
                row.pop('raw_payload',None);row.pop('raw_payload_json',None)
            return row
        observations=[analysis_sample(row) for row in observations]
        live_observation=deepcopy(observations[-1]) if observations else {}
        max_seq=max([0]+[x['event_seq'] for x in events])
        max_time=_latest(*(_value_time(x) for x in observations+events))
        incremental_events=[x for x in events if x['event_seq']>last_seq]
        incremental_observations=[x for x in observations if not last_time or _key(_value_time(x))>_key(last_time)]
        advised_records=self.runtime.native_control(identity,'ADVISED_RECORDS') or []
        incremental_observations += [x for x in observations if x.get('record_id') and x['record_id'] not in advised_records and x not in incremental_observations]
        context_observations=observations[-12:];context_events=events[-20:]
        last_full=next((r for r in reversed(observations) if r.get('source_format')=='V2A_NATIVE_EXPORT_V1'),None)
        if last_full and last_full not in context_observations:context_observations=[last_full,*context_observations]
        previous,previous_input=self.opinions.latest_bundle(symbol,identity)
        eligibility={'advisory_id':previous.get('advisory_id') if previous else None,'eligible':True,'reason':'NO_PREVIOUS'}
        if previous:
            from engines.live.native_health import instant
            try:
                completed=instant(previous.get('ai_completed_at') or previous.get('generated_at'))
                available=bool(completed and completed<=self.clock())
            except (ValueError,TypeError):available=False
            valid_identity=(previous.get('symbol')==member['symbol'] and previous.get('tracking_session_id')==identity
                and previous.get('runtime_mode',self.runtime_mode)==self.runtime_mode)
            native_ok=not getattr(self.workspace,'native_facts_only',False) or previous_input.get('native_provenance_version')=='1'
            window_ok=available and _key(previous.get('data_through_time'))<=_key(max_time)
            eligibility.update(eligible=bool(valid_identity and native_ok and window_ok),
                reason='ELIGIBLE' if valid_identity and native_ok and window_ok else 'UNTRUSTED_PROVENANCE_OR_FUTURE_WINDOW')
            if not eligibility['eligible']:previous,previous_input=None,None
        incremental_times=[_value_time(x) for x in incremental_observations+incremental_events]
        context_times=[_value_time(x) for x in context_observations+context_events]
        window={'incremental_window_start':last_time or _earliest(*incremental_times),'incremental_window_end':_latest(*incremental_times) or max_time,
                'context_window_start':_earliest(*context_times),'context_window_end':_latest(*context_times) or max_time,
                'input_event_seq_from':incremental_events[0]['event_seq'] if incremental_events else None,
                'input_event_seq_to':incremental_events[-1]['event_seq'] if incremental_events else None,
                'input_observation_time_from':_earliest(*(_value_time(x) for x in incremental_observations)),
                'input_observation_time_to':_latest(*(_value_time(x) for x in incremental_observations))}
        market={'incremental_evidence':{'events':incremental_events,'observations':incremental_observations},
                'context_evidence':{'events':context_events,'observations':context_observations,
                    'historical_summary':({k:previous.get(k) for k in ('advisory_id','generated_at','action','dominant_side','dominance_score','core_conflict')} if previous else None)},
                'current_state':analysis_sample(deepcopy(source.get('current_state',{}))),'live_observation':live_observation,
                'data_through_event_seq':max_seq,'data_through_time':max_time,'data_through_observation_time':_latest(*(_value_time(x) for x in observations)),**window}
        market['trigger_events']=incremental_events # v1.0 provider compatibility
        market['delta_since_previous']=self._delta(market,previous_input)
        data_hash=hashlib.sha256(canonical({'event_seq':max_seq,'time':max_time,'incremental':market['incremental_evidence']}).encode()).hexdigest()
        body={'schema_version':'1.1','source':'LIVE_ADVISORY','runtime_mode':self.runtime_mode,
              'simulation_session_id':None,
              'source_session_date':session_date,
              'symbol':member['symbol'],'name':member.get('name') or member['symbol'],
              'tracking_session_id':identity,'session_date':session_date,'source_handoff_id':source.get('handoff_id'),
              'source_handoff_generated_at':source.get('generated_at'),'trigger_type':trigger_type,
              'previous_advisory':deepcopy(previous) if previous else None,**market}
        body['source_session']={k:member.get(k) for k in ('native_export','lifecycle','source_errors','source_owner','source_watermark')}
        body['all_event_sequences']=[e['event_seq'] for e in events]
        body['trigger_events']=incremental_events # v1.0 provider compatibility
        advised_triggers=self.runtime.native_control(identity,'ADVISED_TRIGGERS') or []
        body['live_triggers']=[r for r in (self.runtime.native_control(identity,'LIVE_TRIGGERS') or []) if r['trigger_id'] not in advised_triggers]
        body['trigger_events']=[{**e,'source':'V2A_NATIVE','native_source':e.get('source')} for e in incremental_events]+body['live_triggers']
        body['source_freshness']=self._freshness(session_date,max_time,self.effective(symbol))
        from engines.live.native_health import health as native_health,instant
        body['market_health']=native_health(member,self.clock(),self.market_is_open)
        body['previous_eligibility']=eligibility
        if getattr(self.workspace,'native_facts_only',False):body['native_provenance_version']='1'
        if getattr(self.workspace,'native_facts_only',False) and not observations:
            body['data_completeness']='LIMITED_EVIDENCE'
            body['missing_evidence']=['NATIVE_OBSERVATION_NOT_EXPORTED']
        if member.get('native_export'):
            status=body['market_health']['status']
            body['source_freshness'].update(status='STALE' if status in ('STALE','CLOSE_TAIL_MISSING','SOURCE_ERROR') else 'FRESH' if status in ('FRESH','CLOSE_COMPLETE','LUNCH_BREAK') else 'UNKNOWN',
                latest_data_time=member.get('last_observation_time'),basis='NATIVE_OBSERVATION')
            full_rows=[r for r in observations if r.get('source_format')=='V2A_NATIVE_EXPORT_V1']
            body['data_completeness']='COMPLETE' if full_rows and full_rows[-1].get('quality')=='COMPLETE' else 'LIMITED_EVIDENCE'
            if any(r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1' and r.get('price') is not None for r in observations):
                body['data_completeness']='SNAPSHOT_AVAILABLE' if not full_rows else body['data_completeness']
                if not full_rows:body['missing_evidence']=['FIVE_MINUTE_STRUCTURE_MISSING']
        if member.get('source_owner')=='MARKET_DATA_AGENT':
            body['evidence_validation']={'version':QUALITY_VERSION,'events':[validate_event(e,observations,member) for e in incremental_events+body['live_triggers']]}
            refs={(r.get('record_id'),r.get('sha256'),r.get('available_at')) for e in body['evidence_validation']['events'] for r in e.get('evidence_refs',[])}
            present={r.get('record_id') for r in incremental_observations+context_observations}
            # Earlier comparison facts must accompany their immutable references,
            # even when they precede the last successful analysis cursor.
            body['comparison_observations']=[deepcopy(r) for r in observations if r.get('record_id') not in present
                and (r.get('record_id'),r.get('native_sha256'),r.get('available_at')) in refs]
        # Engine guard covers the full market payload, including native metadata
        # and previous judgment. Unknown/late captured values cannot sneak in.
        if getattr(self.workspace,'native_facts_only',False):
            visible=self.clock()
            def guard(value):
                if isinstance(value,list):
                    for child in value:guard(child)
                elif isinstance(value,dict):
                    for key,child in value.items():
                        if key in ('available_at','as_of','sampled_at','interval_end','market_observed_at','source_updated_at','trade_source_captured_at','boardMedianCapturedAt','timestamp','detected_at','requested_time','requestedTime','intervalEnd','stockDataTime','capturedAt') and child:
                            try:parsed=instant(child,session_date)
                            except (ValueError,TypeError):raise BridgeError('ADVISORY_TIME_UNPROVEN')
                            if parsed>visible:raise BridgeError('ADVISORY_FUTURE_DATA')
                        if isinstance(child,(dict,list)):guard(child)
            guard(market)
            guard(body.get('evidence_validation',{}))
            guard(body.get('comparison_observations',[]))
        body['source_namespace']=self.source
        try:body['portfolio_context']=self.portfolio_context(symbol)
        except Exception as error:
            body['portfolio_context']={'status':'ERROR','error_code':getattr(error,'code','ACCOUNT_UNAVAILABLE'),
                'ai_execution_mode':'OFF','execution_allowed':False,'position':None}
        body.update(time_metadata(body,observations,events,self._stamp()))
        body['evaluation_context_hash']=fingerprint({'portfolio':portfolio_key(body['portfolio_context'])})
        body['reevaluation_reason']='ACCOUNT_CHANGED' if self._account_changed(body) else None
        config=model_settings or self.effective(symbol)
        if config.get('semantic_id'):
            from adapters.ai.capabilities import freeze
            body['model_config']=freeze({k:v for k,v in config.items() if k in ('provider','model','api_mode','base_url','api_key_env','reasoning_effort','effective_reasoning_effort','max_output_tokens','context_tokens','model_max_output_tokens','timeout_seconds','http_attempt_limit','structured_outputs','allow_json_fallback','enabled','capability_version','semantic_id','config_revision')},PROMPT,self.schema)
        value_hash=hashlib.sha256(canonical(body).encode()).hexdigest()
        return {**body,'input_id':'ADVIN-'+value_hash[:32],'input_hash':value_hash,'data_hash':data_hash,'created_at':self._stamp()}

    def _account_changed(self,frozen):
        _,prior=self.opinions.latest_bundle(frozen['symbol'],frozen['tracking_session_id'])
        return bool(prior and portfolio_key(prior.get('portfolio_context',{}))!=portfolio_key(frozen['portfolio_context']))

    @staticmethod
    def _newer(frozen,cursor):
        if not cursor:return True
        return bool(frozen.get('reevaluation_reason') or frozen.get('live_triggers') or any(x.get('record_id') for x in frozen['incremental_evidence']['observations'])) or frozen['data_through_event_seq']>cursor['last_advised_event_seq'] or _key(frozen.get('data_through_observation_time'))>_key(cursor['last_advised_observation_time'])

    @staticmethod
    def _important(events,settings):
        allowed=set(settings.get('important_event_types') if settings.get('important_event_types') is not None else DEFAULT_IMPORTANT_EVENTS)
        return any((row.get('type') or row.get('event_type') or row.get('composite_type')) in allowed or str(row.get('severity') or row.get('level','')).upper() in ('IMPORTANT','CRITICAL') for row in events)

    def eligibility(self,frozen,settings,*,display=False):
        """One qualification authority, with separate rule, quality and scheduling counts."""
        from engines.live.native_health import instant
        identity=frozen['tracking_session_id'];session=frozen.get('source_session',{})
        events=list(frozen['incremental_evidence']['events']);new_count=len(events);blockers=[]
        mode=settings['auto_ai_mode'];types=settings.get('auto_event_types');agent=session.get('source_owner')=='MARKET_DATA_AGENT'
        if mode=='OFF':blockers.append('AUTO_OFF')
        if settings['provider_status']['status']!='READY':blockers.append('PROVIDER_NOT_READY')
        if session.get('source_errors') or self.runtime.ingestion(identity).get('errors'):blockers.append('SOURCE_ERROR')
        if session.get('lifecycle') in ('STOPPED','HISTORICAL','DELETED','CLOSED','DROPPED'):blockers.append('SESSION_INACTIVE')
        if not agent and frozen.get('data_completeness')=='LIMITED_EVIDENCE':blockers.append('LIMITED_EVIDENCE')
        if session.get('native_export'):
            baseline=self.runtime.native_control(identity,'BACKFILL_BASELINE')
            if baseline is None:blockers.append('BACKFILL_INITIALIZING');events=[]
            else:events=[e for e in events if e['event_seq']>baseline['event_seq'] and _key(_value_time(e))>_key(baseline.get('observation_time'))]
            if new_count and not events and not frozen.get('live_triggers'):blockers.append('BACKFILL_ONLY')
        if agent:
            boundary=self.runtime.native_control(identity,'AUTO_POLICY_BOUNDARY')
            if boundary is None:blockers.append('AUTO_BOUNDARY_REQUIRED');events=[]
            else:events=[e for e in events if e['event_seq']>boundary['event_seq']]
        triggers=list(frozen.get('live_triggers',[]));candidates=events+triggers
        if not self._newer(frozen,self.runtime.cursor(identity)):blockers.append('NO_NEW_DATA')
        if not candidates:blockers.append('NO_NEW_EVENTS')
        if types is not None:
            candidates=[e for e in candidates if (e.get('type') or e.get('event_type')) in types]
            if not types:blockers.append('EVENT_FILTER_EMPTY')
            elif not candidates and (events or triggers):blockers.append('EVENT_TYPE_FILTERED')
        else:candidates=[e for e in candidates if not e.get('trigger_id')]
        if mode=='IMPORTANT_ONLY':
            candidates=[e for e in candidates if self._important([e],settings)]
            if not candidates and (events or triggers):blockers.append('NOT_IMPORTANT')
        matched=list(candidates);quality=[];validation=frozen.get('evidence_validation',{})
        if agent:
            by_id={r['event_id']:r for r in validation.get('events',[])}
            for e in candidates:
                check=deepcopy(by_id.get(e.get('event_id') or e.get('trigger_id'),{'missing':['VALIDATION_MISSING'],'status':'INSUFFICIENT'}))
                if validation.get('version')!=QUALITY_VERSION:check.update(status='INSUFFICIENT',missing=['QUALITY_VERSION_UNSUPPORTED'])
                try:age=(self.clock()-instant(e.get('timestamp'),frozen['session_date'])).total_seconds()
                except (ValueError,TypeError):age=None
                if age is None or age<0 or age>settings.get('auto_event_max_age_seconds',900):check.update(status='INSUFFICIENT',missing=check.get('missing',[])+['EVENT_OUTSIDE_VALID_WINDOW'])
                quality.append(check)
            candidates=[e for e,q in zip(candidates,quality) if q['status']=='SUFFICIENT']
            if matched and not candidates:blockers.append('EVENT_EVIDENCE_INSUFFICIENT')
        window_key=fingerprint({'session':identity,'events':[e.get('event_id') or e.get('trigger_id') or e.get('event_seq') for e in candidates]})
        attempted=self.runtime.native_control(identity,'AUTO_WINDOW_ATTEMPT') if agent else None
        if attempted and attempted.get('key')==window_key and attempted.get('state') in ('SUBMITTED','FAILED'):blockers.append('FAILED_WINDOW' if attempted['state']=='FAILED' else 'WINDOW_ALREADY_SUBMITTED')
        failure=self.runtime.latest_failure(identity)
        if failure and failure.get('source_hash')==frozen['data_hash'] and 'FAILED_WINDOW' not in blockers:blockers.append('FAILED_WINDOW')
        if frozen['source_freshness']['status']=='STALE':blockers.append('STALE_SOURCE')
        eligible=[] if blockers else candidates
        if display and self.listener_state() in ('STOPPED','STOPPING'):blockers.insert(0,'LISTENER_STOPPED')
        reason=blockers[0] if blockers else 'ELIGIBLE'
        return {'auto_mode':mode,'allowed_event_types':types,'configuration_origin':settings.get('configuration_origin'),
                'important_event_types':settings.get('important_event_types'),'reason_code':reason,'reason_text':MESSAGES[reason],
                'blockers':blockers,'reasons':[MESSAGES[k] for k in blockers], 'new_event_count':new_count,
                'matched_event_count':sum(not e.get('trigger_id') for e in matched),
                'quality_event_count':sum(not e.get('trigger_id') for e in candidates),
                'evidence_checks':quality,'auto_window_key':window_key,
                'eligible_event_count':sum(not e.get('trigger_id') for e in eligible),
                'eligible_trigger_count':sum(bool(e.get('trigger_id')) for e in eligible),
                'eligible_count':len(eligible),'eligible':bool(eligible) and not blockers,'events':eligible}

    def establish_auto_boundary(self,symbol,not_before=None):
        facts=self.workspace.advisory_facts(symbol);session=facts['session']
        if session.get('source_owner')!='MARKET_DATA_AGENT':return
        sequence=session.get('source_event_max',0)
        if not_before:
            from engines.live.native_health import instant
            cutoff=instant(not_before)
            # First discovery after a persisted enable: only facts newer than that
            # actual user action may pass. Missing times stay excluded, never guessed.
            old=[e.get('event_seq',0) for e in facts['events'] if not e.get('timestamp') or instant(e['timestamp'],session['session_date'])<=cutoff]
            sequence=max(old,default=0)
        self.runtime.save_native_control(session['tracking_session_id'],'AUTO_POLICY_BOUNDARY',{
            'version':'1','event_seq':sequence,'source_watermark':session.get('source_watermark'),
            'created_at':self._stamp(),'enabled_after':not_before,'reason':'NEW_POLICY_APPLIES_TO_FUTURE_EVENTS'})

    def analysis_status(self,symbol,frozen,latest,settings):
        identity=frozen['tracking_session_id'];eligible=self.eligibility(frozen,settings,display=True)
        eligible.pop('events');read=self.runtime.native_control(identity,'READ_POSITION') or {}
        request=self.runtime.active_request(identity) or self.runtime.latest_request(identity)
        task={'task_id':None,'state':'IDLE','source':None,'requested_at':None,'started_at':None,'finished_at':None}
        failure=None
        if request:
            payload=request['payload'];meta=payload.get('task',{});old=payload.get('frozen',{})
            state={'COMPLETED':'SUCCEEDED','INTERRUPTED':'CANCELLED'}.get(request['status'],request['status'])
            task.update(task_id=request['request_id'],state=state,source=meta.get('source') or ('AUTO' if old.get('trigger_type')=='AUTO_EVENT' else 'MANUAL'),
                        requested_at=meta.get('requested_at') or old.get('requested_at') or old.get('created_at'),
                        started_at=meta.get('started_at'),finished_at=meta.get('finished_at'),
                        frozen_input_cutoff=old.get('data_through_at'),opinion_id=meta.get('opinion_id'),model_config=old.get('model_config'))
            if state=='FAILED':
                failure=meta.get('failure')
                old_failure=self.runtime.latest_failure(identity)
                if not failure and old_failure and old_failure['request_id']==request['request_id']:failure=legacy_failure(old_failure)
                if not failure:failure={'stage':'UNKNOWN','error_code':'HISTORICAL_FAILURE_UNCLASSIFIED','retryable':None}
        if task['state'] not in ('RUNNING','QUEUED') and self.runtime.pending(identity) and eligible['eligible']:
            task={**task,'state':'ELIGIBLE','reason':'WAITING_AGGREGATION'}
        return {'schema_version':'1','symbol':symbol,'tracking_session_id':identity,
                'latest_market_time':frozen['data_through_at'],
                'latest_fact_version':fingerprint({'session':identity,'max_event':frozen['data_through_event_seq'],
                    'records':[(r.get('record_id'),_value_time(r)) for r in frozen['context_evidence']['observations']]}),
                'latest_successful_analysis':None if not latest else {'opinion_id':latest['advisory_id'],'cutoff':latest.get('data_through_at') or latest.get('data_through_time'),
                    'completed_at':latest.get('ai_completed_at') or latest['generated_at']},
                'current_task':task,'pending':{'has_new_data':self._newer(frozen,self.runtime.cursor(identity)),
                    'new_event_count':eligible['new_event_count'],'unread_event_count':sum(e['event_seq']>read.get('event_seq',0) for e in frozen['context_evidence']['events']) if not frozen.get('all_event_sequences') else sum(e>read.get('event_seq',0) for e in frozen['all_event_sequences']),
                    'matched_event_count':eligible['matched_event_count'],'quality_event_count':eligible['quality_event_count'],
                    'eligible_event_count':eligible['eligible_event_count'],'eligible_trigger_count':eligible['eligible_trigger_count'],
                    'queued_count':self.runtime.queued_count(identity)},'eligibility':eligible,'failure':failure}

    def _change_severity(self,analysis,previous):
        if not previous:return 'NOTICE'
        if analysis.get('previous_hypothesis_review',{}).get('status')=='INVALIDATED' or analysis.get('action')=='EXIT':return 'CRITICAL'
        if analysis.get('action')!=previous.get('action') or analysis.get('dominant_side')!=previous.get('dominant_side'):return 'IMPORTANT'
        delta=abs(float(analysis.get('dominance_score',0))-float(previous.get('dominance_score',0)))
        return 'IMPORTANT' if delta>=1.5 else 'NOTICE' if delta>=.5 else 'INFO'

    def _perform(self,frozen,settings,request_id):
        started=datetime.now(timezone.utc)
        failure_stage='PROVIDER'
        try:
            with self._provider_slots:
                if self.runtime.retired(frozen['tracking_session_id']):raise BridgeError('TRACKING_DELETED')
                if frozen['trigger_type']=='AUTO_EVENT':
                    current=self.effective(frozen['symbol'])
                    if any(current.get(k)!=settings.get(k) for k in ('auto_ai_mode','auto_event_types','important_event_types')):raise BridgeError('AUTO_SETTINGS_CHANGED','自动分析范围已变化，原排队任务未调用AI。',409)
                ai_started_at=self._stamp()
                self.diagnostics.record(task_id=request_id,symbol=frozen['symbol'],stage='PROVIDER',state='RUNNING',input_id=frozen['input_id'],cutoff=frozen['data_through_at'])
                arguments=(frozen,settings['provider'],settings['model'],settings['reasoning_effort'],PROMPT,self.schema)
                if hasattr(self.provider,'analyze_recorded'):
                    result=self.provider.analyze_recorded(*arguments,request_store=self.opinions.store.path('provider_requests'))
                else:result=self.provider.analyze(*arguments)
            failure_stage='SCHEMA'
            analysis=result.get('analysis')
            try:jsonschema.validate(analysis,self.schema)
            except (jsonschema.ValidationError,TypeError):raise BridgeError('ADVISORY_SCHEMA_ERROR','AI意见未通过结构校验，上一条有效意见已保留。',502) from None
            previous=frozen.get('previous_advisory');review=analysis['previous_hypothesis_review']
            review.update({'previous_advisory_id':previous.get('advisory_id') if previous else None,'previous_generated_at':previous.get('generated_at') if previous else None,
                           'previous_dominant_side':previous.get('dominant_side') if previous else None,'previous_dominance_score':previous.get('dominance_score') if previous else None,
                           'previous_action':previous.get('action') if previous else None})
            jsonschema.validate(analysis,self.schema)
            stamp=self._stamp();action=ACTION_ALIASES.get(analysis['action'],analysis['action']);delta=deepcopy(frozen['delta_since_previous'])
            delta['action']={'previous':previous.get('action') if previous else None,'current':action,'changed':bool(previous and previous.get('action')!=action)}
            old_score=previous.get('dominance_score') if previous else None
            delta['dominance_score']={'previous':old_score,'current':analysis['dominance_score'],'change':round(analysis['dominance_score']-old_score,2) if isinstance(old_score,(int,float)) else None,'direction':analysis['dominance_trend']}
            opinion={'schema_version':'1.1','advisory_id':new_id('ADV'),'request_id':request_id,
                'runtime_mode':self.runtime_mode,'source_namespace':self.source,'simulation_session_id':None,
                'source_session_date':frozen['session_date'],
                'symbol':frozen['symbol'],'name':frozen['name'],
                'tracking_session_id':frozen['tracking_session_id'],'session_date':frozen['session_date'],'generated_at':stamp,
                'data_through_time':frozen['data_through_time'],'data_through_event_seq':frozen['data_through_event_seq'],
                **{k:frozen.get(k) for k in ('incremental_window_start','incremental_window_end','context_window_start','context_window_end','input_event_seq_from','input_event_seq_to','input_observation_time_from','input_observation_time_to')},
                'source_freshness':frozen['source_freshness']['status'],'trigger_type':frozen['trigger_type'],'trigger_events':frozen['incremental_evidence']['events'],
                'provider':result.get('provider') or settings['provider'],'model':result.get('model') or settings['model'],
                'reasoning_effort':result.get('reasoning_effort') or settings['reasoning_effort'],
                'latency_ms':result.get('latency_ms',round((datetime.now(timezone.utc)-started).total_seconds()*1000)),
                'input_id':frozen['input_id'],'delta_since_previous':delta,'action_semantics':action_definition(action),
                'change_severity':self._change_severity({**analysis,'action':action},previous),**analysis,'action':action}
            opinion.update({k:frozen.get(k) for k in ('triggered_at','requested_at','input_frozen_at','data_through_at','incremental_window','context_window','source_field_times','structure_through_at','quote_through_at','request_sequence','reevaluation_reason','live_triggers')})
            opinion.update(ai_started_at=ai_started_at,ai_completed_at=stamp)
            if frozen.get('model_config'):opinion['model_config']=frozen['model_config']
            opinion['upstream_request_id']=result.get('upstream_request_id')
            if result.get('http_attempts'):opinion['provider_request_diagnostics']=result['http_attempts']
            if result.get('usage'):opinion['provider_usage']=result['usage']
            latest=self.opinions.latest(frozen['symbol'],frozen['tracking_session_id'])
            opinion['effective_result']=not self.runtime.retired(frozen['tracking_session_id']) and (not latest or self.opinions.effective_key(opinion)>=self.opinions.effective_key(latest))
            failure_stage='PERSISTENCE'
            self.opinions.append(frozen,opinion)
            self.runtime.commit_success(frozen,opinion)
            if not opinion['effective_result']:
                self.runtime.record_portfolio_outcome(opinion['advisory_id'],{'status':'BLOCKED','reason':'SUPERSEDED_ANALYSIS'},stamp)
                return opinion
        except Exception as error:
            code=getattr(error,'code','ADVISORY_PROVIDER_ERROR')
            failure=failure_metadata(error,failure_stage,self._stamp())
            self.diagnostics.record(task_id=request_id,symbol=frozen['symbol'],state='FAILED',**failure)
            self.runtime.annotate_request(request_id,failure=failure)
            self.runtime.record_failure({'request_id':request_id,'tracking_session_id':frozen['tracking_session_id'],'symbol':frozen['symbol'],'error_code':code,'detail':canonical(failure),'failed_at':self._stamp(),'source_hash':frozen['data_hash']})
            if isinstance(error,BridgeError):
                if getattr(error,'failure_metadata',None) is not None:
                    error.failure_metadata={**failure,'task_id':request_id}
                raise
            raise BridgeError('ADVISORY_PROVIDER_ERROR','AI分析失败，上一条有效意见已保留，可重试。',502) from None
        # Once the opinion is saved, downstream execution cannot turn it into an AI failure.
        try:
            with self._locks_guard:
                superseded=self.runtime.request_superseded(frozen['symbol'],frozen.get('request_sequence',0))
                context_changed=False;current_context={}
                if frozen['portfolio_context'].get('status')!='ERROR':
                    current_context=self.portfolio_context(frozen['symbol'])
                    context_changed=fingerprint(portfolio_key(current_context))!=fingerprint(portfolio_key(frozen['portfolio_context']))
                outcome=({'status':'BLOCKED','reason':'TRACKING_DELETED'} if self.runtime.retired(frozen['tracking_session_id']) else
                    {'status':'BLOCKED','reason':'SUPERSEDED_ANALYSIS'} if superseded else
                    {'status':'BLOCKED','reason':('ACCOUNT_BINDING_CHANGED' if current_context.get('binding_version')!=frozen['portfolio_context'].get('binding_version') else 'NEW_RISK_PAUSED' if current_context.get('new_risk_paused') and opinion.get('portfolio_plan',{}).get('portfolio_action') in ('OPEN','ADD') else 'ACCOUNT_CONTEXT_CHANGED')} if context_changed else
                    {'status':'BLOCKED','reason':'ACCOUNT_UNAVAILABLE'} if frozen['portfolio_context'].get('status')=='ERROR'
                    else {'status':'BLOCKED','reason':'MARKET_EVIDENCE_INCOMPLETE'} if frozen.get('data_completeness')=='LIMITED_EVIDENCE'
                    else self.portfolio_result(opinion,frozen))
        except Exception as error:
            outcome={'status':'FAILED','reason':getattr(error,'code','ACCOUNT_EXECUTION_ERROR'),
                     'advisory_id':opinion['advisory_id'],'account_id':frozen.get('portfolio_context',{}).get('account_id')}
        self.runtime.record_portfolio_outcome(opinion['advisory_id'],outcome,self._stamp())
        return opinion

    def analyze(self,symbol,*,trigger_type='MANUAL',force=False):
        if not self.accepting:raise BridgeError('RUNTIME_DRAINING','后台正在安全收尾，暂不接收新分析。',409)
        if trigger_type not in ('AUTO_EVENT','MANUAL') or type(force) is not bool:raise BridgeError('INVALID_ADVISORY_REQUEST')
        symbol=symbol.lower();request_id=new_id('ADVREQ');requested_at=self._stamp()
        self.diagnostics.record(task_id=request_id,symbol=symbol,stage='INPUT',state='REQUESTED',requested_at=requested_at)
        try:
            settings=self.effective(symbol);readiness=settings['provider_status']
            if readiness['status']!='READY':raise BridgeError(readiness['reason'],'AI配置不可用；市场事实继续同步，请检查AI设置。',503)
            frozen=self.freeze(symbol,'MANUAL_REANALYSIS' if force and trigger_type=='MANUAL' else trigger_type,settings);identity=frozen['tracking_session_id']
            if not frozen['context_evidence']['events'] and not frozen['context_evidence']['observations']:
                raise BridgeError('NO_MARKET_DATA','尚无可信市场数据，等待来源更新。',409)
            if trigger_type=='AUTO_EVENT':
                qualification=self.eligibility(frozen,settings)
                if not qualification['eligible']:return {'status':'AUTO_BLOCKED','reason':qualification['reason_code'],'symbol':symbol}
                frozen['auto_qualification']={k:v for k,v in qualification.items() if k!='events'}
                frozen['auto_window_key']=qualification['auto_window_key']
        except Exception as error:
            try:identity=self.workspace.advisory_facts(symbol)['session']['tracking_session_id']
            except Exception:identity='UNRESOLVED:'+symbol
            failure=failure_metadata(error,'INPUT',self._stamp())
            self.diagnostics.record(task_id=request_id,symbol=symbol,state='FAILED',**failure)
            self.runtime.record_input_failure(request_id,symbol,identity,{'requested_at':requested_at,'finished_at':self._stamp(),
                'source':'AUTO' if trigger_type=='AUTO_EVENT' else 'MANUAL','failure':failure})
            if isinstance(error,BridgeError):raise
            raise BridgeError('INPUT_BUILD_FAILED','无法构建可信分析输入，尚未调用AI。',503) from None
        with self._locks_guard:
            # A day can expire while input construction is outside the scheduler
            # gate. Recheck before enqueue/charging, not only while reading facts.
            if self.runtime.expired(identity):
                error=BridgeError('RETENTION_EXPIRED','已按保留策略清理；此输入不会提交给AI。',status=410)
                failure=failure_metadata(error,'INPUT',self._stamp())
                self.runtime.record_input_failure(request_id,symbol,identity,{'requested_at':requested_at,'finished_at':self._stamp(),'failure':failure})
                self.diagnostics.record(task_id=request_id,symbol=symbol,state='FAILED',**failure)
                raise error
            window_key=fingerprint({'session':identity,'data':frozen['data_hash'],'context':frozen['evaluation_context_hash'],
                'explicit_reanalysis_model':frozen.get('model_config',{}).get('analysis_signature') or model_key(settings) if force else None})
            existing=self.runtime.matching_request(symbol,window_key)
            if existing:
                return {'status':'PENDING_AGGREGATION','queued':True,'coalesced':True,'request_id':existing['request_id'],
                        'data_through_at':frozen['data_through_at'],'tracking_session_id':identity,'symbol':symbol}
            if trigger_type=='AUTO_EVENT' and frozen['source_session'].get('source_owner')=='MARKET_DATA_AGENT':
                self.runtime.save_native_control(identity,'AUTO_WINDOW_ATTEMPT',{'key':frozen['auto_window_key'],'state':'SUBMITTED','request_id':request_id,'at':self._stamp()})
            sequence=self.runtime.enqueue_request(request_id,frozen,settings,force)
            frozen['request_sequence']=sequence
            frozen['input_hash']=hashlib.sha256(canonical(frozen).encode()).hexdigest()
            frozen['input_id']='ADVIN-'+frozen['input_hash'][:32]
            payload={'frozen':frozen,'settings':settings,'force':force,'task':{'window_key':window_key,'requested_at':requested_at,
                'source':'AUTO' if trigger_type=='AUTO_EVENT' else 'MANUAL'}}
            self.runtime.request_status(request_id,'QUEUED',payload)
            if not self.runtime.begin_request(identity,frozen['symbol'],request_id,self._stamp()):
                return {'status':'PENDING_AGGREGATION','queued':True,'request_id':request_id,'data_through_at':frozen['data_through_at'],'tracking_session_id':identity,'symbol':frozen['symbol']}
            self.runtime.request_status(request_id,'RUNNING')
        return self._execute_request(request_id,payload)

    def _recover_saved(self,frozen):
        """Recover only runtime markers from an already committed immutable fact."""
        identity=frozen['tracking_session_id'];cursor=self.runtime.cursor(identity)
        latest,source=self.opinions.latest_bundle(frozen['symbol'],identity)
        if not latest or (cursor and cursor['last_advisory_id']==latest['advisory_id']):return None
        previous=self.opinions.by_id(cursor['last_advisory_id']) if cursor else None
        if previous and self.opinions.effective_key(previous)>=self.opinions.effective_key(latest):return None
        self.runtime.commit_success(source,latest)
        # A failed task never initiated execution. Recovery must not silently do so.
        if self.runtime.portfolio_outcome(latest['advisory_id']) is None:
            self.runtime.record_portfolio_outcome(latest['advisory_id'],{'status':'BLOCKED','reason':'PERSISTENCE_RECOVERY_REQUIRES_REVIEW'},self._stamp())
        self.runtime.annotate_request(latest['request_id'],recovered_at=self._stamp(),opinion_id=latest['advisory_id'])
        self.runtime.request_status(latest['request_id'],'COMPLETED')
        if source['data_hash']==frozen['data_hash'] and source['evaluation_context_hash']==frozen['evaluation_context_hash']:return latest
        return None

    def _execute_request(self,request_id,payload):
        frozen,settings,force=payload['frozen'],payload['settings'],payload['force']
        identity,symbol=frozen['tracking_session_id'],frozen['symbol'];trigger_type=frozen['trigger_type']
        try:
            with self._symbol_lock(symbol.lower()):
                self.runtime.annotate_request(request_id,started_at=self._stamp())
                recovered=self._recover_saved(frozen)
                if force:recovered=None  # Recovery repairs markers; an explicit new analysis remains explicit.
                cursor=self.runtime.cursor(identity)
                # Recheck consumption, without changing the queued frozen input.
                check=deepcopy(frozen)
                covered=set(self.runtime.native_control(identity,'ADVISED_RECORDS') or [])
                check['incremental_evidence']['observations']=[r for r in check['incremental_evidence']['observations'] if not r.get('record_id') or r['record_id'] not in covered]
                covered_triggers=set(self.runtime.native_control(identity,'ADVISED_TRIGGERS') or [])
                check['live_triggers']=[r for r in check.get('live_triggers',[]) if r['trigger_id'] not in covered_triggers]
                check['reevaluation_reason']=self._account_changed(frozen)
                if not recovered and not force and not self._newer(check,cursor):raise BridgeError('NO_NEW_ADVISORY_DATA','自上次分析以来暂无新数据。',409)
                if frozen['source_freshness']['status']=='STALE' and trigger_type=='AUTO_EVENT':raise BridgeError('STALE_SOURCE_AUTO_PAUSED','V2A数据已延迟，自动AI暂停。',409)
                rest_phase=frozen.get('market_health',{}).get('market_phase') in ('LUNCH_BREAK','CLOSED','NON_TRADING_DAY')
                trusted_rest=rest_phase and not frozen.get('market_health',{}).get('errors')
                if frozen['source_freshness']['status']=='STALE' and not force and not trusted_rest:raise BridgeError('STALE_SOURCE_CONFIRM_REQUIRED','当前数据已延迟；确认后可按陈旧数据强制分析。',409)
                result=recovered or self._perform(frozen,settings,request_id)
                self.runtime.annotate_request(request_id,finished_at=self._stamp(),opinion_id=result['advisory_id'])
                self.runtime.request_status(request_id,'COMPLETED' if result.get('effective_result',True) else 'SUPERSEDED')
                try:self.success_observer({'namespace':self.source,'opinion_id':result['advisory_id']})
                except Exception:pass  # Bounded owner feed recovers registration; never fail analysis.
                if frozen.get('auto_window_key'):
                    self.runtime.save_native_control(identity,'AUTO_WINDOW_ATTEMPT',{'key':frozen['auto_window_key'],'state':'SUCCEEDED','request_id':request_id,'at':self._stamp()})
                self.diagnostics.record(task_id=request_id,symbol=symbol,stage='PERSISTENCE',state='SUCCEEDED' if result.get('effective_result',True) else 'SUPERSEDED',opinion_id=result['advisory_id'],completed_at=self._stamp())
                return result
        except Exception as error:
            code=getattr(error,'code',None)
            if frozen.get('auto_window_key'):
                self.runtime.save_native_control(identity,'AUTO_WINDOW_ATTEMPT',{'key':frozen['auto_window_key'],'state':'FAILED','request_id':request_id,'at':self._stamp()})
            state='NO_NEW_DATA' if code=='NO_NEW_ADVISORY_DATA' else 'CONFIRMATION_REQUIRED' if code=='STALE_SOURCE_CONFIRM_REQUIRED' else 'FAILED'
            self.runtime.annotate_request(request_id,finished_at=self._stamp())
            existing=self.runtime.latest_request(identity)
            if state=='FAILED' and existing and existing['request_id']==request_id and not existing['payload'].get('task',{}).get('failure'):
                self.runtime.annotate_request(request_id,failure=failure_metadata(error,'INPUT',self._stamp()))
            self.runtime.request_status(request_id,state);raise
        finally:
            with self._locks_guard:
                pending=self.runtime.finish_request(identity,self._stamp())
                queued=self.runtime.queued_request(symbol)
                if queued:
                    next_input=queued['payload']['frozen']
                    self.runtime.begin_request(next_input['tracking_session_id'],symbol,queued['request_id'],self._stamp())
                    self.runtime.request_status(queued['request_id'],'RUNNING')
                    self._auto_pool.submit(self._execute_request,queued['request_id'],queued['payload'])
            if pending and self.effective(symbol)['auto_ai_mode']!='OFF':self.poll_auto(wait=False)

    def poll_auto(self,wait=True):
        if not self.accepting:return []
        now=self.clock();generated=[];ready=[]
        for facts in self.current_facts():
            session=facts['session']
            identity,symbol=session.get('tracking_session_id'),session.get('symbol')
            if not identity or not symbol:continue
            settings=self.effective(symbol);mode=settings['auto_ai_mode']
            if session.get('source_owner')=='MARKET_DATA_AGENT' and self.runtime.native_control(identity,'AUTO_POLICY_BOUNDARY') is None:
                intent=self.listener_intent();anchor=intent.get('listener_enabled_at') if intent.get('listener')=='ENABLED' else None
                if anchor and settings.get('updated_at'):
                    anchor=max((anchor,settings['updated_at']),key=lambda x:datetime.fromisoformat(x.replace('Z','+00:00')))
                self.establish_auto_boundary(symbol,anchor);continue
            if mode=='OFF' or settings['provider_status']['status']!='READY':continue
            try:frozen=self.freeze(symbol,'AUTO_EVENT');qualification=self.eligibility(frozen,settings)
            except (BridgeError,OSError) as error:
                self.source_errors[symbol]=getattr(error,'code',type(error).__name__);continue
            if 'BACKFILL_INITIALIZING' in qualification['blockers']:self.runtime.ingest(facts,self._stamp())
            if not qualification['eligible']:continue
            new_events=qualification['events']
            if self.runtime.coordinator(identity).get('state')=='RUNNING':
                self.runtime.save_pending({'tracking_session_id':identity,'first_seen_at':iso_utc(now),'event_seq':max(e.get('event_seq',0) for e in new_events),'observation_time':frozen['data_through_time'],'input_hash':frozen['input_hash']});continue
            pending=self.runtime.pending(identity)
            if not pending:
                self.runtime.save_pending({'tracking_session_id':identity,'first_seen_at':iso_utc(now),'event_seq':max(e.get('event_seq',0) for e in new_events),'observation_time':frozen['data_through_time'],'input_hash':frozen['input_hash']});continue
            if (now-datetime.fromisoformat(pending['first_seen_at'])).total_seconds()>=settings['debounce_seconds']:
                ready.append(symbol)
        def run(symbol):
            try:return self.analyze(symbol,trigger_type='AUTO_EVENT')
            except BridgeError as error:
                if error.code!='STALE_SOURCE_AUTO_PAUSED':raise
        if not wait:
            with self._locks_guard:
                for symbol in ready:
                    active=self._auto_futures.get(symbol)
                    if active is None or active.done():self._auto_futures[symbol]=self._auto_pool.submit(run,symbol)
            return []
        if len(ready)>1:
            with ThreadPoolExecutor(max_workers=min(8,len(ready)),thread_name_prefix='TradingLab-Advisory') as pool:
                generated.extend(value for value in pool.map(run,ready) if value is not None)
        else:
            generated.extend(value for value in (run(symbol) for symbol in ready) if value is not None)
        return generated

    def latest(self,symbol):
        try:identity=self._member(symbol)[1]['tracking_session_id']
        except BridgeError:return None
        return self.opinions.latest(symbol,identity)
    def by_id(self,identity):return self.opinions.by_id(identity)
    def bundle(self,identity):
        opinion=self.by_id(identity)
        return (opinion,self.opinions.input(opinion['input_id'])) if opinion else None
    def execution_bundle(self,identity):
        bundle=self.bundle(identity)
        if not bundle:return None
        opinion,frozen=bundle;latest=self.latest(opinion['symbol'])
        eligible=bool(opinion.get('effective_result',True) and latest and latest['advisory_id']==identity)
        eligible=eligible and model_key(opinion)==model_key(self.effective(opinion['symbol']))
        if opinion.get('request_sequence'):
            eligible=eligible and not self.runtime.request_superseded(opinion['symbol'],opinion['request_sequence'])
        # Read-only execution DTO; the stored opinion and historical bundle stay unchanged.
        return ({**opinion,'effective_result':eligible},frozen)
    def history_expired(self,identity):
        if self.runtime.expired(identity):return True
        # Older imported sessions may have opinions but no ingestion row. The
        # retained success cursor links to an explicit owner expiry marker.
        cursor=self.runtime.cursor(identity)
        return bool(cursor and self.opinions.expired_opinion(cursor['last_advisory_id']))

    def history(self,symbol,limit=50,*,session_identity=None):
        # Display callers may supply the current session from the published read
        # model. Reading saved opinions does not need to reload market facts.
        identity=session_identity or self._member(symbol)[1]['tracking_session_id']
        return self.opinions.history(symbol,limit,identity)
    def timeline(self,symbol,limit=100,*,session_identity=None):
        return [{'advisory_id':x['advisory_id'],'generated_at':x['generated_at'],'action':x['action'],'dominant_side':x['dominant_side'],
                 'dominance_score':x['dominance_score'],'dominance_trend':x['dominance_trend'],'previous_hypothesis_review':x['previous_hypothesis_review']['status'],
                 'summary':x.get('current_state'),'change_severity':x.get('change_severity','INFO')} for x in reversed(self.history(symbol,limit,session_identity=session_identity))]
    def symbol_health(self,symbol,*,latest_opinion=_UNSET):
        _,member=self._member(symbol);identity=member['tracking_session_id'];frozen=self.freeze(symbol,'MANUAL')
        latest=(self.latest(symbol) if latest_opinion is _UNSET else latest_opinion) or {};portfolio=frozen['portfolio_context']
        executions=[x for x in portfolio.get('recent_actions',[]) if x.get('advisory_id')==latest.get('advisory_id') and x.get('advisory_id')]
        outcome=executions[-1] if executions else self.runtime.portfolio_outcome(latest.get('advisory_id'))
        if outcome is None and latest.get('portfolio_plan') and portfolio.get('account_id'):
            outcome={'status':'NOT_RECORDED','reason':'EXECUTION_NOT_RECORDED','advisory_id':latest['advisory_id'],
                     'account_id':portfolio['account_id']}
        ai=self.runtime.coordinator(identity);provider_status=self.effective(symbol)['provider_status']
        ai={**ai,'queued_requests':self.runtime.queued_count(identity)}
        if provider_status['status']!='READY':ai={**ai,'state':'PAUSED_PROVIDER_ERROR','reason':provider_status['reason']}
        return {'schema_version':'1.1','symbol':symbol,'tracking_session_id':identity,'v2a':frozen['source_freshness'],'portfolio':frozen['portfolio_context'],
                'portfolio_execution':outcome,'market':frozen['market_health'],'previous_eligibility':frozen['previous_eligibility'],
                'watcher_eligible':frozen['source_freshness']['status']!='STALE','ai':ai,'provider_status':provider_status,
                'last_failure':self.runtime.latest_failure(identity),'latest_advisory_id':latest.get('advisory_id'),
                'analysis_status':self.analysis_status(symbol,frozen,latest,self.effective(symbol))}
