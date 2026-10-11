"""Portable deployment adapter. Delegates all lifecycle and business authority to existing Owners."""
from pathlib import Path
from contextlib import ExitStack, closing
import argparse,hashlib,importlib.metadata,json,os,socket,sqlite3,subprocess,sys,tempfile,time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
CORE=ROOT/'TradingLab'
DATA=CORE/'data'
AGENT=ROOT/'MarketDataAgent'
PYTHON=ROOT/'runtime/python/python.exe'
NODE=ROOT/'runtime/node/node.exe'
class Blocked(RuntimeError):pass

def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def safe_path(path,boundary=ROOT):
    path=Path(path).absolute();boundary=Path(boundary).resolve()
    for item in (path,*path.parents):
        if item.exists() and item.lstat().st_file_attributes & 1024:raise Blocked('链接路径被拒绝')
    if path.is_file() and path.stat().st_nlink!=1:raise Blocked('硬链接被拒绝')
    if not path.resolve().is_relative_to(boundary) or path.resolve()!=path:raise Blocked('路径越界或存在目录联接，请使用完整独立的本地目录。')
    return path
def configure():
    if (ROOT/'BUILD_INCOMPLETE').exists():raise Blocked('Build is incomplete')
    if (ROOT/'MIGRATION_INCOMPLETE').exists():raise Blocked('数据迁移尚未完成；本目录不可启动，请保留原环境并重新迁移到新目录。')
    for p in (CORE,DATA,AGENT,PYTHON,NODE):safe_path(p)
    if Path(sys.executable).resolve()!=PYTHON.resolve():raise Blocked('请使用包内 Runtime 启动，不能使用系统 Python。')
    for key in ('TRADING_LAB_DATA_ROOT','TRADING_LAB_MARKET_AGENT_ROOT','TRADING_LAB_NODE',
                'TRADING_LAB_SOURCE','TRADING_LAB_TEST_RUN_ID','TRADING_LAB_MANAGED_SERVICE','PYTHONPATH','PYTHONHOME'):
        os.environ.pop(key,None)
    os.environ.update(TRADING_LAB_DATA_ROOT=str(DATA),TRADING_LAB_MARKET_AGENT_ROOT=str(AGENT),
        TRADING_LAB_NODE=str(NODE),TRADING_LAB_SOURCE='USER',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    # Process-local only: no registry/system PATH writes. Existing Owner PowerShell calls still work.
    win=Path(os.environ.get('SystemRoot','C:/Windows'))
    os.environ['PATH']=os.pathsep.join(map(str,(PYTHON.parent,NODE.parent,win/'System32',win,win/'System32/WindowsPowerShell/v1.0')))
    sys.path.insert(0,str(CORE));os.chdir(CORE)
    settings=load(ROOT/'portable.json')
    if settings.get('schema')!=1 or set(settings)-{'schema','web_port','agent_port','profile','open_browser'}:raise Blocked('portable.json 格式不正确。')
    port=settings.get('web_port')
    if type(port)!=int or not 1024<=port<=65535:raise Blocked('网页端口必须为 1024—65535。')
    return settings
def records():
    from app.system.runtime_control import read
    return {'supervisor':read(DATA/'runtime/supervisor.json'),'web':read(DATA/'runtime/web-instance.json'),'agent':read(AGENT/'connection.json')}
def owned(record,service):
    from adapters.runtime_platform import alive
    if not alive(record):return False
    expected=AGENT if service=='agent' else DATA
    if record.get('project')!=str(CORE) or record.get('data_root')!=str(expected):
        raise Blocked('检测到仍在运行的其他目录实例；未接管、停止或写入该实例。')
    if Path(record.get('executable','')).resolve()!=PYTHON.resolve():raise Blocked('运行实例未使用此便携包的 Python，停止操作已阻止。')
    return True
def port_free(port):
    with socket.socket() as s:
        if os.name=='nt':s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:s.bind(('127.0.0.1',port));return True
        except OSError:return False
def verify_manifest():
    manifest=load(ROOT/'runtime/files.json')
    for relative,expected in manifest.items():
        p=safe_path(ROOT/relative)
        if not p.is_file() or digest(p)!=expected:raise Blocked('程序或依赖文件缺失/改变：'+relative+'；请恢复完整发布包，不会自动下载升级。')
    return len(manifest)
def database_paths():
    candidates=list((DATA/'account/unified').glob('AC-*/account.db'))
    candidates += [DATA/p for p in ('account/unified/portfolio-control.db','live/advisory/advisory.db',
        'runtime/live/advisory/advisory_runtime.db','live/advisory/provider_requests/provider_requests.db',
        'live/history/history.db','live/history/provider_requests/provider_requests.db','system/ai-configuration.db','system/notifications/telegram.db')]
    candidates.append(AGENT/'market_agent.db')
    return [safe_path(p) for p in candidates if p.exists()]
def preflight(settings,deep=False):
    if (CORE/'.venv').exists():raise Blocked('便携程序目录中发现旧 .venv；原管理器会优先使用它。请保留在旧安装中，不要混入本包。')
    if sys.version_info[:3]!=(3,12,14) or sys.maxsize<=2**32:raise Blocked('需要包内 Python 3.12.14 Windows x64。')
    import ssl,sqlite3,ctypes,jiter,pydantic_core,rpds,yaml,jsonschema,httpx,openai
    from zoneinfo import ZoneInfo
    ZoneInfo('Asia/Shanghai')
    for line in (CORE/'requirements-lock.txt').read_text().splitlines():
        if line.strip() and not line.startswith('#'):
            name,expected=line.strip().split('==')
            if importlib.metadata.version(name)!=expected:raise Blocked('依赖版本不一致：'+name)
    version=subprocess.check_output([str(NODE),'--version'],text=True,timeout=10).strip()
    if version!='v24.19.0':raise Blocked('需要包内 Node 24.19.0。')
    if deep:print('文件完整性：通过（'+str(verify_manifest())+' 个文件）')
    from dotenv import dotenv_values
    from adapters.baselines import verify_baselines
    if verify_baselines(CORE)['status']!='READY':raise Blocked('冻结参考文件校验失败；没有修改或执行 Legacy。')
    import yaml
    config=yaml.safe_load((CORE/'config/ai.yaml').read_text(encoding='utf-8'))
    if not isinstance(config.get('ai',{}).get('providers'),dict):raise Blocked('AI 配置缺失或格式错误。')
    env={**dotenv_values(CORE/'.env'),**os.environ}
    for name in ('TRADING_LAB_READ_TIMINGS','TRADING_LAB_ANALYSIS_DIAGNOSTICS','TRADING_LAB_AI_HTTP_BUDGET'):
        if env.get(name):
            p=Path(env[name]);p=p if p.is_absolute() else CORE/p
            if not p.resolve().is_relative_to(ROOT):raise Blocked(name+' 指向包外文件；请先迁移对应文件并修正本地配置，未关闭原保护。')
    print('Python 3.12.14 x64 / Node 24.19.0 / 25 项依赖：通过')
    print('凭据：'+('存在本地配置（不显示内容、不验证网络）' if any(env.get(k) for k in ('DEEPSEEK_API_KEY','OPENAI_API_KEY')) else '尚未填写；网页可启动，真实 AI 分析不可用'))
    for p in (DATA,AGENT,ROOT/'logs'):
        safe_path(p);p.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=p) as f:f.write(b'permission check');f.flush()
    checked=0
    for path in database_paths():
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                db.execute('PRAGMA query_only=ON')
                result=db.execute('PRAGMA quick_check(1)').fetchone()
                if result!=('ok',):raise Blocked('数据库检查未通过：'+path.name)
            checked+=1
        except sqlite3.Error as e:raise Blocked('数据库无法读取或被占用：'+path.name+'（'+type(e).__name__+'）') from None
    print('数据库只读检查：'+str(checked)+' 个通过；未迁移结构、未初始化数据库。')
    for service,r in records().items():owned(r,service)
    web=records()['web'];running=owned(web,'web')
    if running:
        from app.system.runtime_control import request
        health=request(web,'/healthz')
        if health.get('instance_id')!=web.get('instance_id') or web.get('url')!=f"http://127.0.0.1:{settings['web_port']}":raise Blocked('当前实例/端口与本包配置不一致。')
    elif not port_free(settings['web_port']):raise Blocked('网页端口 '+str(settings['web_port'])+' 被其他程序占用；请修改 portable.json 的 web_port，未结束任何其他进程。')
    print('端口 '+str(settings['web_port'])+'：'+('本包已运行' if running else '可用'))
    from adapters.market_agent_process import validate_activation
    activated=validate_activation(CORE,AGENT)['enabled']
    print('行情采集：'+('保留原已批准状态' if activated else '未导入有效采集授权；仅启动网页，不自动开启采集'))
    return activated
def status():
    from app.system.runtime_desktop import snapshot,format_status
    # Read-only: do not create status caches just to inspect a portable installation.
    print(format_status(snapshot(CORE,DATA)))
def wait_operation(op,seconds=320):
    from app.system.runtime_control import control_request
    end=time.monotonic()+seconds;next_message=0
    while time.monotonic()<end:
        value=control_request(DATA,{'action':'status'})
        row=next((r for r in value.get('operations',[]) if r['id']==op['id']),None)
        if row and row['status']=='COMPLETED':return
        if row and row['status']=='BLOCKED':raise Blocked('原运行管理器暂缓操作：'+row.get('reason','未知原因'))
        if time.monotonic()>next_message:print('正在等待服务就绪或已有任务安全结束…',flush=True);next_message=time.monotonic()+10
        time.sleep(.25)
    raise Blocked('任务仍未安全结束，已停止等待；没有强杀。请稍后运行 Check.cmd。')
def stop():
    from app.system.runtime_control import control_request,request,Supervisor
    from app.system.runtime_state import RuntimeState
    from adapters.runtime_platform import alive
    before=records()
    for s,r in before.items():owned(r,s)
    if owned(before['supervisor'],'supervisor'):
        wait_operation(control_request(DATA,{'action':'stop','target':'background'})['operation'])
    else:
        # Existing Owner's exact identity / graceful contracts, including supervisor-offline recovery.
        owner=Supervisor(CORE,DATA);RuntimeState(DATA).update({'web':'STOPPED','agent':'STOPPED'})
        for s in ('web','agent'):owner._stop(s)
    current=records()
    if any(alive(current[s]) for s in ('web','agent')):raise Blocked('服务尚未退出；未结束管理者。')
    manager=current['supervisor']
    if owned(manager,'supervisor'):
        request(manager,'/shutdown-supervisor',{'confirm':'RELOAD_SUPERVISOR'})
        end=time.monotonic()+15
        while alive(manager) and time.monotonic()<end:time.sleep(.2)
        if alive(manager):raise Blocked('管理者正在结束；未强杀。')
    print('网页、行情服务及管理者已正常停止；监听期望、账户、分析设置保持不变。')
def start(settings,activated,no_browser=False):
    from app.system.runtime_control import ensure_supervisor,control_request,request
    from app.system.runtime_state import RuntimeState
    from app.system.runtime_desktop import open_once
    from adapters.runtime_platform import alive
    before=records()
    # Portable is explicitly manual startup. Never imports another PC's Windows scheduled task.
    RuntimeState(DATA).update({'startup':'MANUAL'})
    try:
        ensure_supervisor(CORE,DATA,settings['web_port'])
        target='background' if activated else 'web'
        wait_operation(control_request(DATA,{'action':'start','target':target})['operation'],90)
        record=records()['web'];health=request(record,'/healthz')
        if health.get('instance_id')!=record.get('instance_id'):raise Blocked('网页健康检查实例不一致。')
    except Exception:
        # Roll back only a fresh launch; never stop pre-existing services after a failed action.
        if not any(alive(r) for r in before.values()):
            try:stop();print('本次新启动已正常回退。')
            except Exception:print('安全回退尚未完成，请运行 Stop.cmd；没有强杀进程。')
        raise
    print('TradingLab 已就绪：'+record['url']+'/live')
    if settings.get('open_browser',True) and not no_browser:
        result=open_once(DATA,record)
        if result=='OPEN_FAILED':print('浏览器未能自动打开；后台已正常运行，请手动打开上方地址。')
    return 0
def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='TradingLab Portable：本机独立运行入口')
    p.add_argument('action',choices=('start','stop','check','status'))
    p.add_argument('--deep',action='store_true');p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    try:
        settings=configure()
        if settings.get('profile')=='TEST':
            import portable_test_control as isolated
            if args.action=='status':isolated.check(ports=False)
            elif args.action=='check':isolated.check(ports=False)
            else:getattr(isolated,args.action)()
            return 0
        if settings.get('profile','USER')!='USER':raise Blocked('Unknown profile')
        if args.action=='stop':stop()
        elif args.action=='status':status()
        else:
            activated=preflight(settings,args.deep)
            if args.action=='start':start(settings,activated,args.no_browser)
            else:status()
        return 0
    except Exception as error:
        # Never print Provider errors, credentials, subprocess stderr, or full control records.
        message=str(error) if isinstance(error,Blocked) else '检查/操作未完成：'+type(error).__name__+'；请核对文件、目录权限和配置。'
        if isinstance(error,ImportError):message='缺少或无法加载运行依赖：'+str(error.name or '未知模块')+'（'+type(error).__name__+'）；请恢复完整 runtime 目录。'
        print('未完成：'+message,flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
