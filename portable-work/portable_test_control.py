"""Project-owned, offline TEST environment and lifecycle control (Windows x64)."""
from pathlib import Path
import hashlib, importlib, importlib.metadata, json, os, platform, re, shutil, socket, subprocess, sys, time, urllib.request, uuid, venv
PACKAGE=Path(__file__).resolve().parent
ROOT=PACKAGE/'TradingLab'
TEST=ROOT/'sandbox'; BASE=PACKAGE/'runtime/python/python.exe'; PY=BASE; NODE=PACKAGE/'runtime/node/node.exe'
sys.path.insert(0,str(ROOT))
LOCK=json.loads((PACKAGE/'runtime/runtime-lock.json').read_text('utf-8'))
CFG=json.loads((PACKAGE/'portable.json').read_text('utf-8'))
def require(value,message):
    if not value:raise RuntimeError(message)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,value):
    safe(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def safe(p):
    p=Path(p).absolute();require(p.is_relative_to(PACKAGE),'路径越界')
    for item in (p,*p.parents):
        if item.exists():require(not(item.stat(follow_symlinks=False).st_file_attributes & 1024),'链接路径被拒绝')
    if p.is_file():require(p.stat().st_nlink==1,'硬链接被拒绝')
    return p
def files(root):
    safe(root)
    result=[]
    for directory,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:safe(Path(directory)/name)
        result.extend(Path(directory)/name for name in names)
    return sorted(result)
def seal(root):return {p.relative_to(root).as_posix():sha(p) for p in files(root)}
def environment():
    allowed={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','NUMBER_OF_PROCESSORS','OS','HOMEDRIVE','HOMEPATH','USERNAME','COMPUTERNAME'}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    windows=os.environ.get('SystemRoot',r'C:\Windows')
    env.update(PATH=str(NODE.parent)+';'+str(PY.parent)+';'+windows+'\\System32;'+windows+'\\System32\\WindowsPowerShell\\v1.0',
        PSModulePath=windows+'\\System32\\WindowsPowerShell\\v1.0\\Modules',
        TRADING_LAB_NODE=str(NODE),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONNOUSERSITE='1',
        TEMP=str(TEST/'temp'),TMP=str(TEST/'temp'))
    (TEST/'temp').mkdir(exist_ok=True)
    return env
def configuration():
    require(CFG.get('profile')=='TEST','TEST profile required')
    require(CFG['web_port']!=CFG['agent_port'] and all(type(CFG[k]) is int and 1024<CFG[k]<65536 for k in ('web_port','agent_port')),'Invalid ports')
    for p in (TEST,TEST/'data',TEST/'agent',TEST/'logs',TEST/'temp'):safe(p).mkdir(parents=True,exist_ok=True)
    expected={'schema':1,'project':str(ROOT),'source':'TEST','core_data':str(TEST/'data'),'agent_data':str(TEST/'agent')}
    marker=TEST/'data-ownership.json'
    if not marker.exists():
        require(not any((TEST/'data').iterdir()) and not any((TEST/'agent').iterdir()),'Unknown nonempty data roots refused')
        save(marker,expected)
    require(json.loads(marker.read_text('utf-8'))==expected,'Data ownership mismatch')
    files(TEST/'data');files(TEST/'agent')
    require(not (ROOT/'.env').exists(),'TEST profile refuses a real .env')
    source=TEST/'data/system/market-source.json'
    if source.exists():
        config=json.loads(source.read_text('utf-8'))['config']
        require(config.get('source')=='TEST','Core source is not TEST')
        if config.get('market_agent_root'):require(Path(config['market_agent_root']).resolve()==TEST/'agent','Foreign Agent data root')
    # No migration or schema writes: query only owned synthetic databases.
    import sqlite3
    from contextlib import closing
    for p in files(TEST):
        if p.suffix in ('.db','.sqlite','.sqlite3'):
            with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                db.execute('PRAGMA query_only=ON')
                require(db.execute('PRAGMA quick_check(1)').fetchone()==('ok',),'Synthetic database integrity failure')

def port_available(port):
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:s.bind(('127.0.0.1',port));return True
        except OSError:return False
def check(ports=True):
    configuration()
    import portable_control
    portable_control.verify_manifest()
    actual={'python/'+p:h for p,h in seal(PACKAGE/'runtime/python').items()};actual.update({'node/'+p:h for p,h in seal(PACKAGE/'runtime/node').items()})
    require(actual=={r['path']:r['sha256'] for r in LOCK['files']},'Runtime file set mismatch')
    require(sys.version_info[:3]==(3,12,14) and platform.machine().upper() in ('AMD64','X86_64'),'Python 版本或架构不符')
    require(Path(sys.executable).resolve()==PY.resolve() and Path(sys.base_prefix).resolve()==BASE.parent.resolve(),'解释器或基础 Runtime 路径不符')
    require(sha(ROOT/'requirements-lock.txt')==LOCK['requirements_sha256'],'Python 依赖声明与锁不符')
    normalize=lambda s:re.sub('[-_.]+','-',s).lower()
    expected={normalize(k):v for k,v in LOCK['dependencies'].items()}
    installed={normalize(d.metadata['Name']):d.version for d in importlib.metadata.distributions()}
    require(installed==expected,'25 项 Python 依赖版本不匹配')
    imports=('annotated_types','anyio','attrs','certifi','colorama','distro','h11','httpcore','httpx','idna','jiter','jsonschema','jsonschema_specifications','openai','pydantic','pydantic_core','dotenv','yaml','referencing','rpds','sniffio','tqdm','typing_inspection','typing_extensions','tzdata')
    for name in ('ssl','sqlite3','ctypes','_ssl','_sqlite3',*imports):importlib.import_module(name)
    node=json.loads(subprocess.check_output([str(NODE),'-p','JSON.stringify({version:process.versions.node,arch:process.arch,exe:process.execPath})'],text=True,env=environment()))
    require(node['version']=='24.19.0' and node['arch']=='x64' and Path(node['exe']).resolve()==NODE.resolve(),'Node 版本、架构或路径不符')
    from engines.live.market_agent.service import AgentService
    os.environ['TRADING_LAB_NODE']=str(NODE)
    probe=TEST/'checks'/uuid.uuid4().hex
    agent=AgentService(probe,source='TEST',network=False)
    try: worker=agent.query()
    finally:agent.close()
    if ports:require(all(port_available(CFG[k]) for k in ('web_port','agent_port')),'TEST 端口被占用；请停止本包实例或等待占用端口释放')
    result={'status':'PASS','python':platform.python_version(),'executable':sys.executable,'base_prefix':sys.base_prefix,'node':node,'dependency_count':len(installed),'native_imports':'PASS','worker':'PASS','runtime_integrity':'PASS','config':'TEST; no market network / real AI / Telegram','ports':'PASS' if ports else 'NOT_TESTED','second_pc':'NOT_TESTED','browser_e2e':'NOT_TESTED','historical_tool_reference_count':0,'telegram_authorization':'PRIVATE_ONLY; TEST delivery disabled'}
    save(TEST/'check-result.json',result);print(json.dumps(result,ensure_ascii=False))
def request(record,path,payload=None):
    require(re.fullmatch(r'http://127\.0\.0\.1:\d+',record['url']),'控制地址必须 loopback')
    req=urllib.request.Request(record['url']+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Authorization':'Bearer '+record.get('token',''),'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
def owned(record,kind):
    from adapters.runtime_platform import alive
    require(record.get('source')=='TEST' and Path(record['project']).resolve()==ROOT,'进程工程或 TEST 身份不匹配')
    require(Path(record['data_root']).resolve()==TEST/('data' if kind=='web' else 'agent'),'进程数据根不匹配')
    require(Path(record['executable']).resolve() in (PY.resolve(),BASE.resolve()),'进程解释器不匹配')
    require(record['url']==f"http://127.0.0.1:{CFG[kind+'_port']}",'进程端口不匹配')
    if not alive(record):return False
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    handle=kernel.OpenProcess(0x1000,False,record['pid']);require(handle,'无法核验进程路径')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        require(kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)),'无法读取进程路径')
        require(Path(buffer.value).resolve()==Path(record['executable']).resolve(),'实际进程路径与登记不符')
    finally:kernel.CloseHandle(handle)
    return True
def stop():
    from adapters.runtime_platform import alive
    state=TEST/'instances.json'
    if not state.exists():print('PASS：没有登记的 TEST 实例');return
    value=json.loads(state.read_text('utf-8'));require(value['project']==str(ROOT),'实例归属不符')
    for kind in ('web','agent'):
        record=value.get(kind)
        if record and owned(record,kind):
            request(record,'/internal/shutdown' if kind=='web' else '/v1/shutdown',{} if kind=='web' else {'confirm':'STOP_DATA_SERVICE'})
            deadline=time.monotonic()+20
            while alive(record) and time.monotonic()<deadline:time.sleep(.15)
            require(not alive(record),'TEST 正常关闭超时；保留身份和日志，不强杀未知进程')
    value['stopped']=True;save(state,value);print('PASS：TEST Web / Agent 已正常停止')
def start():
    check()
    from adapters.runtime_platform import alive
    prior=TEST/'instances.json'
    if prior.exists():
        previous=json.loads(prior.read_text('utf-8'))
        require(not any(alive(previous[k]) for k in ('web','agent') if previous.get(k)),'已有 TEST 实例，拒绝重复启动')
    env=environment();env.update(TRADING_LAB_SOURCE='TEST',TRADING_LAB_TEST_RUN_ID='tradinglab-portable-test',TRADING_LAB_DATA_ROOT=str(TEST/'data'))
    value={'project':str(ROOT),'run_id':uuid.uuid4().hex};processes=[];jobs=[]
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.restype=ctypes.c_void_p
    kernel.AssignProcessToJobObject.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    kernel.TerminateJobObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    save(prior,value)
    try:
        for kind,entry,args,recordpath in (
            ('agent','market_data_agent.py',['--source','TEST','--start-paused','--data-root',str(TEST/'agent'),'--port',str(CFG['agent_port'])],TEST/'agent/connection.json'),
            ('web','trading_lab.py',['--web-only','--port',str(CFG['web_port']),'--market-agent-root',str(TEST/'agent')],TEST/'data/runtime/web-instance.json')):
            log=TEST/'logs'/f"{value['run_id']}-{kind}.log"
            with log.open('ab') as output:
                proc=subprocess.Popen([str(PY),'-I','-B','-X','utf8',str(PACKAGE/'portable_test_child.py'),entry,*args],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(proc)
            job=kernel.CreateJobObjectW(None,None);require(job,'无法创建 TEST 启动事务')
            jobs.append(job);require(kernel.AssignProcessToJobObject(job,int(proc._handle)),'无法建立 TEST 进程归属')
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                require(proc.poll() is None,'启动失败，查看 '+str(log))
                try:
                    record=json.loads(recordpath.read_text('utf-8'))
                    if owned(record,kind):
                        require(record['pid']==proc.pid or record['parent_pid']==proc.pid,'服务不属于本次启动')
                        value[kind]=record;save(prior,value)
                        health=request(record,'/healthz' if kind=='web' else '/v1/health')
                        require(health.get('instance_id')==record['instance_id'],'健康响应实例身份不符')
                        break
                except (OSError,ValueError,KeyError,RuntimeError):pass
                time.sleep(.2)
            else:raise RuntimeError('等待 TEST 服务超时：'+str(log))
        print('PASS：TradingLab Portable / TEST '+value['web']['url']+'；Agent 为暂停采集的 TEST 实例；使用 Stop.cmd 关闭')
    except BaseException:
        try:stop()
        finally:
            # Jobs contain only processes spawned by this invocation.
            for job in jobs:kernel.TerminateJobObject(job,1)
            for proc in processes:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        raise
    finally:
        for job in jobs:kernel.CloseHandle(job)
def main():
    try:
        {'check':lambda:check(ports=False),'start':start,'stop':stop}[sys.argv[1]]()
    except Exception as error:
        print('FAIL：'+str(error)+'。已停止，请检查 sandbox/logs；勿使用正式数据或全局环境绕过。',file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
