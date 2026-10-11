"""Manual EOD analysis only. No Account, notification, Event or Live cursor capability."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore,Lock,Event,Thread
from uuid import uuid4
import json,re
from contracts.history.bars import HistoryError,request
from engines.history.bars import TZ
from shared.serialization import digest

PROMPT='''你是历史收盘行情分析助手。只分析输入指定股票截至截止交易日收盘的日/周/月事实。这是后验重建日线，不是当时原始快照；不复权可能包含除权跳变。不得引入后续行情、今天账户、行业、新闻或其他意见。量能比较由后端已计算，直接引用实际样本、进度、完整状态，样本不足和未知成交额必须说明。不要把未完成周/月当作完整周期；不生成账户意图或交易执行指令。输出中文：conclusion 本轮结论，basis 核心依据（含明确价格和量能证据及限制），next_observation 接下来应观察的条件（不声称已发生），limitations 数据限制。遵循给定JSON Schema。'''
SCHEMA={'type':'object','additionalProperties':False,'properties':{k:{'type':'string','minLength':1,'maxLength':5000} for k in ('conclusion','basis','next_observation','limitations')},'required':['conclusion','basis','next_observation','limitations']}
PROMPT+=' 完整周期严格以证据说明的完整状态为准；节假日形成的4个交易日周也可能已经完整，禁止假定完整周必须5个交易日，禁止要求已闭合的目标周等待补齐。盘中最高价与收盘价不可混称。面向用户的正文全部使用自然中文，不输出内部变量名、JSON键或枚举；禁止在正文写volume_context、ratio、amount、null等开发字段。缺失时写“成交额数据未提供”；比值写“量比0.72倍”。成交量统一用W股，1W股等于10000股，最多两位小数；价格、成交额、量比不使用W。保留事实、否定、条件、价格与单位，不补造信息。不额外调用翻译或摘要。'

def evidence(frozen,prompt,schema):
    """Explicit portable historical evidence builder; never calls intraday projection."""
    from engines.live.evidence import estimate,encoded
    if frozen.get('mode')!='HISTORY_EOD' or frozen.get('portfolio_context') is not None:raise HistoryError('HISTORY_CONTEXT_INVALID','历史账户上下文必须为空。')
    cutoff=frozen['visible_through'];end=frozen['end_date']
    for bar in frozen['bars']:
        if bar['date']>end or not bar['available_at'] or bar['available_at']>cutoff:raise HistoryError('HISTORY_FUTURE_DATA','历史输入出现未来或未收盘数据。')
        for member in bar['members']:
            if member['date']>end:raise HistoryError('HISTORY_FUTURE_DATA','聚合含未来成分。')
    for row in frozen['volume_context']['samples']:
        if row['end']>end:raise HistoryError('HISTORY_FUTURE_DATA','量能样本晚于截止日。')
    from contracts.live.presentation import volume_summary,volume
    readable=volume_summary(frozen['volume_context'])+'\n成交额数据未提供。以下成交量单位均为股；只分析截至'+end+'收盘的事实。\n'
    readable+='\n'.join(f"{b['date']}：开盘{b['open']}，最高{b['high']}，最低{b['low']}，收盘{b['close']}，成交量{volume(b['volume'])}股，周期{'完整' if b['complete'] else '未完成或证据不足'}。" for b in frozen['bars'])
    prepared={**frozen,'readable_evidence':readable}
    count=estimate(encoded(prepared)+prompt+encoded(schema))+1024
    if count>32000:raise HistoryError('INPUT_BUDGET','历史输入超出安全预算，请减少图表根数。')
    return prepared,{'input_builder_version':'history-eod-2-zh','token_count_method':'CHARACTER_ESTIMATE_NOT_MODEL_TOKENIZER',
        'target_input_tokens':32000,'estimated_input_tokens':count,'source_frozen_input_hash':frozen['input_hash']}

class HistoricalAnalysis:
    def __init__(self,bars,store,provider,settings,source='USER',name_resolver=None):
        self.bars,self.store,self.provider,self.settings,self.source=bars,store,provider,settings,source
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='history-eod');self.slots=BoundedSemaphore(2)
        self.submit_lock=Lock();self.model_configuration=None
        self.name_resolver=name_resolver or (lambda _:None);self.stop=Event();self.maintenance_thread=None;self.maintenance_error=None
    def start_maintenance(self):
        if self.maintenance_thread:return
        self.maintenance_thread=Thread(target=self._maintain,daemon=True,name='history-daily-ttl');self.maintenance_thread.start()
    def _maintain(self):
        while not self.stop.is_set():
            try:self.maintenance_once();self.maintenance_error=None
            except Exception as error:self.maintenance_error=type(error).__name__
            if self.stop.wait(30):break
    def maintenance_once(self):
        result=self.store.expire(self.bars.clock().astimezone(TZ).date().isoformat())
        with self.store.db() as db:rows=db.execute('SELECT DISTINCT symbol FROM result_index WHERE name IS NULL LIMIT 2').fetchall()
        for row in rows:
            name=self.name_resolver(row[0])
            if name:
                with self.store.db() as db:db.execute('UPDATE result_index SET name=? WHERE symbol=? AND name IS NULL',(name,row[0]))
        return result
    def detail(self,identity):
        from contracts.live.presentation import history_display,chinese_prose
        job=self.store.job(identity)
        today=self.bars.clock().astimezone(TZ).date().isoformat()
        if job['used_day']<today and job['status'] not in ('RUNNING','QUEUED'):
            job.update(status='EXPIRED',input=None,opinion=None,error=None,message='已按保留策略清理')
        job['display']=history_display(job)
        job['display']['error']=chinese_prose(job['error']) if job.get('error') else None
        return job
    def submit(self,payload):
        with self.submit_lock:return self._submit(payload)
    def active_work(self):
        with self.store.db() as db:
            return bool(db.execute("SELECT 1 FROM jobs WHERE status IN ('RUNNING','QUEUED') LIMIT 1").fetchone())
    def _submit(self,payload):
        identity=payload.get('request_id','')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',identity):raise HistoryError('REQUEST_ID_REQUIRED','历史分析需要有效请求标识。',400)
        force=payload.get('force_reanalysis',False)
        if type(force) is not bool:raise HistoryError('INVALID_CONFIRMATION','重新分析必须明确确认。',400)
        q=request({k:v for k,v in payload.items() if k not in ('request_id','force_reanalysis','model_selection')})
        with self.store.db() as db:row=db.execute('SELECT id,context FROM jobs WHERE request_id=?',(identity,)).fetchone()
        if row:
            if json.loads(row['context'])!=q:raise HistoryError('REQUEST_ID_CONFLICT','请求标识已用于不同历史窗口。',409)
            job=self.store.job(row['id'])
            if payload.get('model_selection') is not None and self.model_configuration:
                from adapters.ai.capabilities import freeze
                requested=freeze(self.model_configuration.resolve(payload['model_selection']),PROMPT,SCHEMA)
                registered=(job.get('input') or {}).get('model_config') or {}
                if registered.get('analysis_signature')!=requested['analysis_signature']:raise HistoryError('REQUEST_ID_CONFLICT','请求标识已用于另一模型配置。',409)
            return job
        # Freeze once before comparing context. Same data/model cannot trigger accidental billing.
        result=self.bars.read(q);settings=self.settings();catalog=self.provider.catalog()
        provider=settings.get('provider') or catalog['default_provider'];model=settings.get('model') or catalog['default_model'];reasoning=settings.get('reasoning_effort','none')
        model_config=None
        if self.model_configuration:
            from adapters.ai.capabilities import freeze
            try:model_config=freeze(self.model_configuration.resolve(payload.get('model_selection')),PROMPT,SCHEMA)
            except Exception as e:raise HistoryError(getattr(e,'code','INVALID_MODEL_SELECTION'),str(e),400) from None
            provider,model,reasoning=(model_config[k] for k in ('provider','model','reasoning_effort'))
        now=self.bars.clock().astimezone(TZ);day=now.date().isoformat()
        key=self.store.context_key(q,result['data_version'],provider,model,reasoning)
        legacy_key=key
        if model_config:key=digest({'request':q,'data_version':result['data_version'],'analysis_signature':model_config['analysis_signature']})
        existing=self.store.matching(day,key)
        if model_config and not existing and not force:
            legacy=self.store.matching(day,legacy_key)
            if legacy and not (legacy.get('input') or {}).get('model_config'):
                # Never invent old output/prompt settings or silently bill again on upgrade.
                return {**legacy,'reused':True,'model_configuration_unverified':True,
                    'message':'今日已有同窗口旧版意见，完整模型参数未记录；可先查看原结果。使用当前配置重做请明确选择“仍然重新分析”。'}
        if existing and (not force or existing['status'] in ('QUEUED','RUNNING')):
            return {**existing,'reused':True,'message':'今日已有相同历史分析结果' if existing['status']=='SUCCEEDED' else '相同历史分析正在进行，请查看已有任务'}
        with self.store.db() as db:
            size=db.execute('SELECT coalesce(sum(length(input)+coalesce(length(opinion),0)),0) FROM jobs').fetchone()[0]
            if size>16*1024*1024:raise HistoryError('HISTORY_STORAGE_FULL','历史工作空间已达容量上限，等待下一交易日维护。',429)
        if not self.slots.acquire(blocking=False):raise HistoryError('HISTORY_BUSY','已有历史分析正在运行，请稍后重试。',429)
        job='HIST-'+uuid4().hex
        try:
            with self.store.db() as db:
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(job,identity,now.isoformat(),day,'QUEUED',json.dumps(q),json.dumps({'model_config':model_config}),None,None))
                db.execute('INSERT INTO result_index VALUES(?,?,?,?,?,?,?,?,?,?)',(job,day,q['symbol'],None,key,result['data_version'],provider,model,reasoning,None))
            self.pool.submit(self._work,job,q,result,provider,model,reasoning,model_config)
        except BaseException:self.slots.release();raise
        return self.store.job(job)
    def _work(self,job,q,result,provider,model,reasoning,model_config=None):
        try:
            with self.store.db() as db:db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?",(job,))
            end=q['end_date']
            if result['actual_end_date']!=end:raise HistoryError('NOT_TRADING_DAY','所选日期没有该股票有效日线，请选择实际有数据的交易日。')
            if any(not b['available_at'] for b in result['bars']):raise HistoryError('MARKET_NOT_CLOSED','历史分析需等待目标交易日收盘。')
            # Historical input has no fetch-time current quote, name, account, Event or prior Opinion.
            frozen={'mode':'HISTORY_EOD','input_id':job,'context_id':job,'symbol':q['symbol'],'end_date':end,
                'visible_through':end+'T15:00:00+08:00','period':q['period'],'volume_period':q['volume_period'],
                'requested_samples':q['samples'],'adjustment':'NONE','source':result['source'],
                'data_version':result['data_version'],'bars':result['bars'],'volume_context':result['volume_context'],
                'quality':result['quality'],'portfolio_context':None}
            if model_config:frozen['model_config']=model_config
            frozen['input_hash']=digest(frozen);evidence(frozen,PROMPT,SCHEMA)
            with self.store.db() as db:db.execute('UPDATE jobs SET input=? WHERE id=?',(json.dumps(frozen,ensure_ascii=False),job))
            if hasattr(self.provider,'analyze_history'):
                response=self.provider.analyze_history(frozen,provider,model,reasoning,PROMPT,SCHEMA,self.store.root/'provider_requests',self.store.root/'attempts'/(job+'.db'))
            else:raise HistoryError('HISTORY_PROVIDER_UNSUPPORTED','当前测试或适配器未提供隔离历史分析能力。')
            import jsonschema
            analysis=response['analysis'];jsonschema.validate(analysis,SCHEMA)
            opinion={'opinion_id':job,'mode':'HISTORY_EOD','symbol':q['symbol'],'end_date':end,'period':q['period'],
                'volume_period':q['volume_period'],'samples':q['samples'],'actual_samples':result['volume_context']['actual_samples'],
                'generated_at':self.bars.clock().isoformat(),'provider':provider,'model':model,'reasoning':reasoning,
                'input_hash':frozen['input_hash'],'analysis':analysis,'usage':response.get('usage',[]),
                'model_config':model_config,'http_attempts':response.get('http_attempts'),
                'latency_ms':response.get('latency_ms'),'upstream_request_id':response.get('upstream_request_id')}
            completed=self.bars.clock().astimezone(TZ);name=None
            try:name=self.name_resolver(q['symbol'])
            except Exception:pass
            with self.store.db() as db:
                db.execute("UPDATE jobs SET status='SUCCEEDED',opinion=?,used_day=? WHERE id=? AND status='RUNNING'",(json.dumps(opinion,ensure_ascii=False),completed.date().isoformat(),job))
                db.execute('UPDATE result_index SET day=?,name=?,completed_at=? WHERE id=?',(completed.date().isoformat(),name,completed.isoformat(),job))
        except Exception as error:
            failure=getattr(error,'failure_metadata',{})
            message=str(error) if isinstance(error,(HistoryError,)) else '历史分析未完成：'+failure.get('error_code',getattr(error,'code',type(error).__name__))
            with self.store.db() as db:db.execute("UPDATE jobs SET status='FAILED',error=? WHERE id=? AND status='RUNNING'",(message,job))
        finally:self.slots.release()
    def close(self):
        self.stop.set()
        if self.maintenance_thread:self.maintenance_thread.join(10)
        self.pool.shutdown(wait=True,cancel_futures=False)
