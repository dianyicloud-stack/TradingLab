"""Independent local runtime authority. Orchestrates contracts, never business DBs."""
from pathlib import Path
from threading import Event, Thread, RLock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import URLError
from queue import Queue, Empty
import json, os, secrets, subprocess, sys, time, uuid
from app.system.runtime_state import RuntimeState, atomic, stamp, read_json
from adapters.runtime_platform import identity, alive, build, spawn, force_owned
from adapters.runtime_lease import runtime_lease

ACTIONS=('status','start','stop','restart','force-stop','force-restart')
TARGETS=('background','web','agent')

def read(path):
    try:return read_json(path)
    except FileNotFoundError:return {}

def request(record,path,payload=None,timeout=2):
    import re
    if not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}',record.get('url','')):raise ValueError('INVALID_CONTROL_ADDRESS')
    r=Request(record['url']+path,data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+record.get('token',''),'Content-Type':'application/json'})
    with urlopen(r,timeout=timeout) as response:return json.load(response)

def control_request(root,payload):return request(read(Path(root)/'runtime/supervisor.json'),'/control',payload)

class Recovery:
    def __init__(self,clock=time.monotonic):self.clock=clock;self.failures=[];self.next=0;self.stable=None
    def failed(self):
        now=self.clock();self.failures=[x for x in self.failures if now-x<600];self.failures.append(now)
        self.next=now+(5,15,30,60)[min(len(self.failures)-1,3)];self.stable=None
    def healthy(self):
        if self.stable is None:self.stable=self.clock()
        if self.clock()-self.stable>=120:self.failures=[];self.next=0
    def reset(self):self.failures=[];self.next=0;self.stable=None
    def allowed(self):return len(self.failures)<5 and self.clock()>=self.next
    def status(self):return {'attempts':len(self.failures),'recovery_paused':len(self.failures)>=5,'retry_in_seconds':max(0,round(self.next-self.clock(),1))}

class Supervisor:
    def __init__(self,project,root,port=8765):
        from adapters.source_configuration import source_configuration
        self.project,self.root=Path(project).resolve(),Path(root).resolve();self.port=port
        self.state=RuntimeState(root);_,self.config=source_configuration(self.project,self.root,'USER',None)
        self.agent_root=Path(self.config['market_agent_root']).resolve()
        self.stop=Event();self.lock=RLock();self.queue=Queue(maxsize=16);self.services={};self.operations=[]
        self.recovery={s:Recovery() for s in ('web','agent')};self.unresponsive={};self.instance=uuid.uuid4().hex
        self.processes={};self.control_revision=0
        self.build_id=build(self.project)
        self.manager_error=None
    def descriptor(self,service):
        path=self.root/'runtime/web-instance.json' if service=='web' else self.agent_root/'connection.json'
        record=read(path)
        if not record:return {}
        if record.get('project')!=str(self.project) or record.get('data_root')!=str(self.root if service=='web' else self.agent_root):
            # Never adopt old PID-only records. A free owner lease is required to start.
            return {}
        return record
    def inspect(self,service):
        record=self.descriptor(service)
        if not alive(record):return {'actual':'STOPPED','checked_at':stamp()}
        try:
            response=request(record,'/healthz' if service=='web' else '/v1/health')
            if response.get('instance_id')!=record.get('instance_id'):raise ValueError('INSTANCE_MISMATCH')
            self.unresponsive.pop(service,None)
            result={'actual':'RUNNING','pid':record['pid'],'instance_id':record['instance_id'],'build':record.get('build'),
                'checked_at':stamp(),'progress':response.get('progress'),'collection':response.get('collection'),
                'error':response.get('error')}
            # Cheap owner status; no market calls, DB scans or business locks.
            if service=='web':result['runtime']=request(record,'/internal/runtime')
            return result
        except (OSError,ValueError):
            first=self.unresponsive.setdefault(service,time.monotonic())
            return {'actual':'UNRESPONSIVE','pid':record['pid'],'instance_id':record['instance_id'],
                'checked_at':stamp(),'reason':'LOCAL_CONTROL_UNRESPONSIVE','unresponsive_seconds':round(time.monotonic()-first,1),
                'message':'本机控制暂未响应；未按行情或AI耗时强杀服务。可选择强制重启。'}
    def status(self):
        with self.lock:return {'status':'RUNNING','instance_id':self.instance,'build':self.build_id,'supervisor':identity(),
            'desired':self.state.read(),'services':dict(self.services),'operations':self.operations[-8:],'manager_error':self.manager_error}
    def submit(self,payload):
        if set(payload)-{'action','target','expected_revision'}:raise ValueError('INVALID_CONTROL_FIELDS')
        action=payload.get('action');target=payload.get('target','background')
        if action not in ACTIONS or target not in TARGETS:raise ValueError('INVALID_CONTROL_COMMAND')
        if action=='status':return self.status()
        with self.lock:
            if self.queue.full():raise ValueError('CONTROL_QUEUE_FULL')
            targets=('web','agent') if target=='background' else (target,)
            changes={s:'RUNNING' if action=='start' else 'STOPPED' for s in targets} if action in ('start','stop','force-stop') else {}
            desired=self.state.update(changes,payload.get('expected_revision'))
            self.control_revision+=1
            op={'id':uuid.uuid4().hex,'action':action,'target':target,'revision':self.control_revision,'status':'QUEUED','at':stamp()}
            self.operations.append(op);self.operations=self.operations[-16:];self.queue.put(op)
            for service in targets:self.recovery[service].reset()
            return {'operation':dict(op),'desired':desired}
    def _lease_free(self,service):
        with runtime_lease(self.root if service=='web' else self.agent_root):pass
    def _released(self,service,record):
        if alive(record):return False
        try:self._lease_free(service)
        except RuntimeError:return False
        process=self.processes.get(service)
        if process:
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:return False
        return True
    def _start(self,service):
        value=self.inspect(service)
        if value['actual']!='STOPPED':return
        self._lease_free(service)
        env=dict(os.environ);env['TRADING_LAB_DATA_ROOT']=str(self.root);env['TRADING_LAB_SOURCE']='USER'
        env['TRADING_LAB_MANAGED_SERVICE']=service
        executable=str(self.project/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python'))
        if not Path(executable).is_file():executable=sys.executable
        if service=='web':cmd=[executable,'-B',str(self.project/'trading_lab.py'),'--managed','--port',str(self.port)]
        else:
            from adapters.market_agent_process import validate_activation
            if not validate_activation(self.project,self.agent_root)['enabled']:raise ValueError('AGENT_ACTIVATION_REQUIRED')
            cmd=[executable,'-B',str(self.project/'market_data_agent.py'),'--data-root',str(self.agent_root),'--source','USER','--enable-market-network']
        if service=='web' and self.port:
            import socket
            with socket.socket() as probe:
                probe.settimeout(.3)
                if probe.connect_ex(('127.0.0.1',self.port))==0:raise ValueError('UNVERIFIED_PROCESS_OWNS_WEB_PORT')
        self.processes[service]=spawn(cmd,self.project,self.root/f'runtime/service-logs/{service}.log',env)
        end=time.monotonic()+20
        while time.monotonic()<end:
            value=self.inspect(service)
            if value['actual']=='RUNNING':return
            if self.processes[service].poll() is not None:raise ValueError('SERVICE_START_EXITED')
            time.sleep(.15)
        raise ValueError('SERVICE_START_TIMEOUT')
    def _stop(self,service,force=False,force_after=False):
        record=self.descriptor(service)
        if not alive(record):self._lease_free(service);return
        if not force:
            try:request(record,'/internal/shutdown' if service=='web' else '/v1/shutdown',
                {} if service=='web' else {'confirm':'STOP_DATA_SERVICE','preserve_activation':True})
            except (OSError,ValueError):
                if not force_after:raise ValueError('GRACEFUL_CONTROL_UNAVAILABLE_USE_EXPLICIT_FORCE')
            end=time.monotonic()+(10 if force_after else 300)
            while time.monotonic()<end:
                if self._released(service,record):return
                with self.lock:self.services[service]={**self.inspect(service),'actual':'DRAINING','message':'等待已有分析、业务操作和所有者写入安全结束。'}
                time.sleep(.5)
            if not force_after:raise ValueError('GRACEFUL_DRAIN_PENDING_NO_FORCE_USED')
        force_owned(record,self.project,self.root if service=='web' else self.agent_root,service)
        end=time.monotonic()+15
        while time.monotonic()<end:
            if self._released(service,record):return
            time.sleep(.1)
        raise ValueError('EXIT_NOT_CONFIRMED')
    def execute(self,op):
        op.update(status='RUNNING',started_at=stamp())
        try:
            targets=('web','agent') if op['target']=='background' else (op['target'],)
            if op['action']!='start':
                for service in targets:self._stop(service,op['action']=='force-stop',op['action']=='force-restart')
            for service in reversed(targets):
                # Re-read latest intent: a newer STOP wins even while an old restart drains.
                if self.state.read()[service]=='RUNNING' and op['action'] in ('start','restart','force-restart'):self._start(service)
            op.update(status='COMPLETED',finished_at=stamp())
        except Exception as error:op.update(status='BLOCKED',reason=str(error)[:160],finished_at=stamp())
    def tick(self):
        for service in ('agent','web'):
            desired=self.state.read()[service];value=self.inspect(service);recovery=self.recovery[service]
            if value['actual']=='RUNNING':recovery.healthy()
            if desired=='STOPPED' and value['actual']=='RUNNING':
                try:self._stop(service);value=self.inspect(service)
                except Exception as error:value.update(reason=str(error)[:160])
            elif value['actual']=='STOPPED' and desired=='RUNNING' and recovery.allowed():
                try:self._start(service);recovery.failed();value=self.inspect(service)
                except Exception as error:
                    recovery.failed();value.update(reason=str(error)[:160])
                    if any(code in str(error) for code in ('ACTIVATION','ACCESS','SCHEMA','MISMATCH','UNVERIFIED','ALREADY_RUNNING')):
                        recovery.failures=[time.monotonic()]*5
            with self.lock:self.services[service]={**value,**recovery.status()}
    def run(self):
        while not self.stop.is_set():
            try:op=self.queue.get(timeout=.5)
            except Empty:op=None
            try:
                if op:self.execute(op)
                self.tick();self.manager_error=None
            except Exception as error:self.manager_error=type(error).__name__+':'+str(error)[:120]
            self.stop.wait(2)

def serve(project,root,port=8765):
    root=Path(root).resolve()
    os.environ['TRADING_LAB_MANAGED_SERVICE']='supervisor';os.environ['TRADING_LAB_DATA_ROOT']=str(root)
    from shared.logging import configure_logging
    configure_logging()
    with runtime_lease(root/'runtime/supervisor-lease'):
        supervisor=Supervisor(project,root,port);token=secrets.token_hex(32)
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    if self.path not in ('/control','/shutdown-supervisor') or self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin') is not None or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):raise ValueError('CONTROL_ACCESS_DENIED')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<1024 or self.headers.get('Transfer-Encoding'):raise ValueError('CONTROL_BODY_INVALID')
                    payload=json.loads(self.rfile.read(length))
                    if self.path=='/shutdown-supervisor':
                        if payload!={'confirm':'RELOAD_SUPERVISOR'}:raise ValueError('INVALID_CONFIRMATION')
                        if any(o['status'] in ('QUEUED','RUNNING') for o in supervisor.operations):raise ValueError('CONTROL_OPERATION_ACTIVE')
                        result={'status':'STOPPING','services_preserved':True};supervisor.stop.set()
                        Thread(target=self.server.shutdown,daemon=True).start()
                    else:result=supervisor.submit(payload)
                    code=200
                except (ValueError,TypeError) as error:result={'error':str(error)};code=400
                data=json.dumps(result,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        atomic(root/'runtime/supervisor.json',{**identity(),'project':str(Path(project).resolve()),'data_root':str(root),
            'instance_id':supervisor.instance,'token':token,'url':f'http://127.0.0.1:{server.server_port}'})
        Thread(target=supervisor.run,daemon=True,name='runtime-supervisor').start()
        try:server.serve_forever()
        finally:supervisor.stop.set();server.server_close()

def ensure_supervisor(project,root,port=8765):
    try:return control_request(root,{'action':'status'})
    except (OSError,ValueError):pass
    record=read(Path(root)/'runtime/supervisor.json')
    if alive(record):raise ValueError('SUPERVISOR_CONTROL_UNRESPONSIVE')
    command=[sys.executable,'-B',str(Path(project)/'tools/runtime_control.py'),'serve','--port',str(port)]
    env=dict(os.environ);env['TRADING_LAB_DATA_ROOT']=str(root)
    # Detached supervisor owns its lifecycle and its own bounded log. No terminal PIPE.
    if os.name=='nt' and RuntimeState(root).read()['startup'] in ('LOGON','BOOT'):
        from adapters.runtime_windows import launch
        launch(project)
    else:
        subprocess.Popen(command,cwd=project,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0),start_new_session=os.name!='nt')
    end=time.monotonic()+15
    while time.monotonic()<end:
        try:return control_request(root,{'action':'status'})
        except (OSError,ValueError):time.sleep(.2)
    raise ValueError('SUPERVISOR_START_FAILED')
