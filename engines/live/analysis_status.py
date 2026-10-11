"""Live analysis outcome vocabulary. No market facts are altered by status."""
import json
import sqlite3

MESSAGES={
 'EVENT_EVIDENCE_INSUFFICIENT':'所选事件缺少其规则需要的证据，详情列出缺失项；新证据到达后重新检查。',
 'AUTO_BOUNDARY_REQUIRED':'等待建立新自动分析起点，历史事件不会补发。',
 'WINDOW_ALREADY_SUBMITTED':'此事件窗口已经提交；等待原任务，不重复调用。',
 'AUTO_OFF':'该股票已关闭自动分析。',
 'PROVIDER_NOT_READY':'AI配置不可用，请检查模型设置。',
 'SOURCE_ERROR':'来源校验异常，自动分析暂停。',
 'SESSION_INACTIVE':'当前跟踪会话未处于活动状态。',
 'LIMITED_EVIDENCE':'周期观察的完整性尚未证实，自动分析暂停；可手动分析已有可信事实。',
 'BACKFILL_INITIALIZING':'正在建立实时起点，历史补读不触发自动分析。',
 'NO_NEW_DATA':'自上次成功分析后没有新的可分析事实。',
 'NO_NEW_EVENTS':'有行情变化，但没有新的自动触发事件。',
 'BACKFILL_ONLY':'新增事件属于历史补读，不触发自动分析。',
 'EVENT_FILTER_EMPTY':'未选择任何自动分析事件类型。',
 'EVENT_TYPE_FILTERED':'本批事件类型不在已选自动分析范围。',
 'NOT_IMPORTANT':'当前仅分析重要事件，本批事件不符合重要级别或配置类别。',
 'FAILED_WINDOW':'该窗口最近分析失败，自动重试已暂停；请按失败原因处理。',
 'STALE_SOURCE':'市场数据时效不满足自动分析条件。',
 'LISTENER_STOPPED':'实时监听未启动，不会自动提交分析；仍可手动分析。',
 'ELIGIBLE':'事件符合自动分析条件，等待聚合或调度。'}

def failure_metadata(error,stage,stamp):
    # Never persist str(error): providers and schema validators can include prompts.
    provided=getattr(error,'failure_metadata',None)
    if provided:return {**provided,'occurred_at':stamp}
    code=getattr(error,'code',None);retryable=None
    if code in ('API_KEY_MISSING','AUTH_FAILED','MODEL_INVALID','PROVIDER_NOT_CONFIGURED'):stage='CONFIGURATION';retryable=False
    elif stage=='PERSISTENCE':code='PERSISTENCE_FAILED';retryable=True
    elif stage=='INPUT':code=code or 'INPUT_BUILD_FAILED';retryable=False
    elif isinstance(error,TimeoutError):code='PROVIDER_TIMEOUT';retryable=True
    elif isinstance(error,(ConnectionError,OSError)) and not isinstance(error,sqlite3.Error):code='PROVIDER_NETWORK_ERROR';retryable=True
    elif isinstance(error,json.JSONDecodeError):code='PROVIDER_PARSE_ERROR';retryable=True
    elif code=='ADVISORY_SCHEMA_ERROR':code='PROVIDER_SCHEMA_ERROR';stage='SCHEMA';retryable=True
    elif code in ('API_KEY_MISSING','AUTH_FAILED','MODEL_INVALID'):stage='CONFIGURATION';retryable=False
    elif code=='DAILY_PROVIDER_FAILED':stage='PROVIDER';retryable=None
    else:code=code or 'INTERNAL_ERROR'
    return {'stage':stage,'error_code':code,'retryable':retryable,'occurred_at':stamp}

def legacy_failure(row):
    if not row:return None
    # Historical generic transport failures cannot be retroactively classified.
    code=row['error_code']
    return {'stage':'PROVIDER' if code in ('DAILY_PROVIDER_FAILED','ADVISORY_PROVIDER_ERROR') else 'SCHEMA' if code=='ADVISORY_SCHEMA_ERROR' else 'UNKNOWN',
            'error_code':code,'retryable':None,'occurred_at':row['failed_at'],'task_id':row['request_id']}
