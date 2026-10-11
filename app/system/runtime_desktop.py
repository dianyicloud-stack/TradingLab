"""Human-facing local CLI: presentation, bounded waits, browser handoff.

Lifecycle authority remains runtime_control; business settings are read through APIs.
"""
from pathlib import Path
import time,webbrowser
from app.system.runtime_control import control_request,ensure_supervisor,read,Supervisor
from app.system.runtime_state import RuntimeState,atomic,stamp
from adapters.runtime_platform import alive
from adapters.runtime_lease import runtime_lease

LABELS={'RUNNING':'运行中','STOPPED':'未运行','UNRESPONSIVE':'未响应','DRAINING':'正在等待任务结束',
    'ENABLED':'开启','DISABLED':'关闭','WATCHING':'正常监听','STARTING':'启动中','DEGRADED':'正在重连',
    'NON_TRADING_DAY':'休市等待','BEFORE_OPEN':'盘前等待','LUNCH_BREAK':'午休等待','CLOSED':'收盘等待',
    'WAITING_FIRST_DATA':'等待首份可信数据','WAITING_ELIGIBLE_EVENT':'正常监听，等待合格事件',
    'SOURCE_CONNECTION_ERROR':'来源连接异常，后台重连中','USER_STOPPED':'已主动停止',
    'MAINTENANCE_PAUSED':'后台已暂停，长期设置保留','AUTO_SHADOW_EXECUTION':'自动影子执行',
    'ADVISORY_ONLY':'仅建议','OFF':'关闭','none':'不启用额外推理','low':'低','medium':'中','high':'高','max':'最高',
    'GRACEFUL_DRAIN_PENDING_NO_FORCE_USED':'任务仍在安全收尾，未强制结束。可稍后查看状态。',
    'GRACEFUL_CONTROL_UNAVAILABLE_USE_EXPLICIT_FORCE':'正常停止接口暂不可用；未强制结束服务。',
    'UNVERIFIED_PROCESS_OWNS_WEB_PORT':'网页端口被其他实例占用，未重复启动。',
    'AGENT_ACTIVATION_REQUIRED':'行情采集尚未启用。','SERVICE_START_EXITED':'服务启动后退出，请查看运行中心或服务日志。',
    'SUPERVISOR_START_FAILED':'运行管理者未能启动，请核对本机运行环境。','SERVICE_START_TIMEOUT':'服务未在期限内就绪。'}
def label(value):return LABELS.get(value,value or '尚未取得')

def snapshot(project,root):
    try:return control_request(root,{'action':'status'})
    except (OSError,ValueError):
        inspector=Supervisor(project,root)
        record=read(Path(root)/'runtime/supervisor.json')
        return {'status':'UNRESPONSIVE' if alive(record) else 'STOPPED','desired':RuntimeState(root).read(),
            'services':{s:inspector.inspect(s) for s in ('web','agent')}}

def web_get(record,path):
    # Read the exact instance URL published by the existing owner.
    from app.system.runtime_control import request
    return request(record,path)

def business_summary(root):
    root=Path(root);path=root/'runtime/desktop-status.json';cached=read(path)
    record=read(root/'runtime/web-instance.json')
    try:
        if not alive(record):return cached,True
        health=web_get(record,'/healthz')
        if health.get('instance_id')!=record.get('instance_id'):return cached,True
        binding=web_get(record,'/api/accounts/execution-binding')
        model=web_get(record,'/api/system/ai')['default']
        notice=web_get(record,'/api/system/telegram')
        value={'measured_at':stamp(),'binding':{k:binding.get(k) for k in ('name','mode','new_risk_paused')},
            'model':{k:model.get(k) for k in ('provider','model','reasoning_effort')},
            'telegram':{'enabled':notice.get('enabled'),'configured':notice.get('state') not in ('NO_TOKEN','INVALID_CHAT','DISABLED'),
                        'message':notice.get('message')}}
        atomic(path,value);return value,False
    except (OSError,ValueError,KeyError):return cached,True

def format_status(value,business=None,cached=False):
    desired=value.get('desired',{});services=value.get('services',{});web=services.get('web',{})
    listener=web.get('runtime',{}).get('listener',{})
    lines=['TradingLab 后台状态','',f"Supervisor：{label(value.get('status'))}",f"Web：{label(web.get('actual'))}",
        f"Market Data Agent：{label(services.get('agent',{}).get('actual'))}",'',
        '实时监听：',f"  期望状态：{label(desired.get('listener'))}",
        f"  实际状态：{label(listener.get('reason') or listener.get('actual')) if web.get('actual')=='RUNNING' else '后台未运行或不可达，监听期望设置保留'}"]
    if business:
        if cached:lines+=['',f"以下为上次已确认设置（{business.get('measured_at','未知时间')}），本次未重新核对："]
        b=business.get('binding',{});m=business.get('model',{});n=business.get('telegram',{})
        lines+=['',f"执行账户：{b.get('name') or '未绑定'}",f"账户模式：{label(b.get('mode'))}",
            f"新增风险：{'已暂停' if b.get('new_risk_paused') is True else '允许' if b.get('new_risk_paused') is False else '尚未取得'}",'',
            f"AI模型：{ {'deepseek':'DeepSeek','openai':'OpenAI'}.get(m.get('provider'),m.get('provider') or '尚未取得')} / {m.get('model','尚未取得')} / {label(m.get('reasoning_effort'))}",
            f"Telegram：{'未启用' if not n.get('enabled') else '已配置（不代表已送达）' if n.get('configured') else '尚未完成配置'}"]
    else:lines+=['','账户、模型、通知设置：Web启动后可读取。']
    lines+=['',f"Windows登录自启动：{'已关闭' if desired.get('startup')=='MANUAL' else '已设置登录启动' if desired.get('startup')=='LOGON' else '请核对启动设置'}"]
    return '\n'.join(lines)

def open_once(root,record,opener=webbrowser.open):
    root=Path(root);path=root/'runtime/desktop-browser.json'
    try:
        with runtime_lease(root/'runtime/desktop-browser-lease'):
            if read(path).get('instance_id')==record.get('instance_id'):return 'ALREADY_OPENED'
            try:opened=opener(record['url']+'/live',new=2)
            except Exception:return 'OPEN_FAILED'
            if not opened:return 'OPEN_FAILED'
            atomic(path,{'instance_id':record['instance_id'],'opened_at':stamp()});return 'OPENED'
    except (OSError,RuntimeError):return 'OPEN_FAILED'

def wait_result(root,op,action,emit=print,timeout=None):
    end=time.monotonic()+(timeout if timeout is not None else 70 if action=='start' else 315)
    message_at=0
    while time.monotonic()<end:
        value=control_request(root,{'action':'status'})
        current=next((x for x in value.get('operations',[]) if x['id']==op['id']),None)
        if current and current['status']=='BLOCKED':raise RuntimeError(label(current.get('reason')))
        if current and current['status']=='COMPLETED':
            return value
        if time.monotonic()>=message_at:
            emit('正在等待任务结束，未使用强制停止…' if action=='stop' else '正在启动后台，等待服务就绪…',flush=True)
            message_at=time.monotonic()+10
        time.sleep(.25)
    raise RuntimeError('等待超时；后台操作可能仍在进行，请打开“TradingLab 状态”核对。未强制结束服务。')

def run(project,root,action,port=8765,emit=print):
    if action not in ('start','stop','status'):raise ValueError('桌面入口仅支持启动、停止和状态。')
    before=snapshot(project,root)
    if action=='status':
        business,cached=business_summary(root);emit(format_status(before,business,cached));return 0
    if action=='stop':
        business_summary(root) # Minimal owner DTO for offline display; never copies business facts.
        if before['status']=='STOPPED' and all(x['actual']=='STOPPED' for x in before['services'].values()):
            emit('TradingLab 已停止，监听长期设置保持不变。');return 0
        result=control_request(root,{'action':'stop','target':'background'})
        wait_result(root,result['operation'],action,emit)
        emit('TradingLab 网页与行情采集已正常停止。\n实时监听长期设置已保留；轻量本机管理者保留待命。');return 0
    already=before['status']=='RUNNING' and all(before.get('services',{}).get(s,{}).get('actual')=='RUNNING' for s in ('web','agent'))
    if not already:
        ensure_supervisor(project,root,port)
        result=control_request(root,{'action':'start','target':'background'})
        wait_result(root,result['operation'],action,emit)
    record=read(Path(root)/'runtime/web-instance.json')
    health=web_get(record,'/healthz')
    if health.get('instance_id')!=record.get('instance_id'):raise RuntimeError('网页实例校验失败，未打开浏览器。')
    # Operation completion and lightweight local health are both required.
    emit('TradingLab 已经运行。' if already else 'TradingLab 启动成功。')
    business_summary(root)
    browser=open_once(root,record)
    emit('网页已交给默认浏览器打开。' if browser=='OPENED' else '本次网页已打开过，不重复创建页面。' if browser=='ALREADY_OPENED' else '后台已启动，但默认浏览器未能打开；请手动打开以下地址。')
    emit(record['url']+'/live');return 0
