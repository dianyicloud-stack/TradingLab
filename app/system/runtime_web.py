"""Web lifecycle contract; task owners report work and retain recovery authority."""
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread
import time
from contracts.live.bridge import BridgeError
from app.system.runtime_state import RuntimeState, stamp

class WebRuntime:
    def __init__(self,root,loop,history,notifications):
        self.state=RuntimeState(root,clock=lambda:loop.advisory._stamp());self.loop=loop;self.history=history;self.notifications=notifications
        self.stop_event=Event();self.lock=Lock();self.quiescing=False;self.inflight=0;self.server=None
        self.started=None;self.reason=None;self.thread=None
        loop.intent=self.state
        loop.advisory.listener_intent=self.state.read
    @contextmanager
    def command(self,path):
        control=path.startswith('/api/system/runtime') or path in ('/api/live/listener/stop','/api/live/listener/start')
        with self.lock:
            if self.quiescing and not control:raise BridgeError('RUNTIME_DRAINING','后台正在安全收尾，暂不接收新操作。',409)
            self.inflight+=1
        try:yield
        finally:
            with self.lock:self.inflight-=1
    def start(self):
        if self.thread:return
        def reconcile():
            while not self.stop_event.is_set():
                try:
                    with self.lock:
                        if not self.quiescing:self.loop.reconcile()
                except Exception as error:self.reason=type(error).__name__
                self.stop_event.wait(1)
        self.thread=Thread(target=reconcile,daemon=True,name='runtime-listener-intent');self.thread.start()
    def status(self):
        return {'listener':self.loop.runtime_status(),'quiescing':self.quiescing,'reason':self.reason,
                'drain_seconds':round(time.monotonic()-self.started,1) if self.started else 0,'inflight_commands':self.inflight}
    def shutdown(self):
        with self.lock:
            if self.quiescing:return self.status()
            self.quiescing=True;self.started=time.monotonic();self.reason='WAITING_OWNER_TASKS'
            self.loop.advisory.accepting=False;self.loop.stop(persist=False)
        def drain():
            # Not a kill timeout. Controller reports bounded wait; work may finish later.
            while not self.stop_event.wait(.25):
                if self.inflight or self.loop.poll_lock.locked():continue
                if self.loop.advisory.active_work() or self.history.active_work():continue
                if not self.notifications.lock.acquire(False):continue
                try:self.notifications.stop.set();self.notifications.wake.set()
                finally:self.notifications.lock.release()
                self.reason='OWNERS_DRAINED'
                if self.server:self.server.shutdown()
                return
        Thread(target=drain,daemon=True,name='runtime-graceful-drain').start()
        return self.status()
    def close(self):
        self.stop_event.set();self.loop.stop(persist=False)
        if self.thread:self.thread.join(3)
        if self.loop.thread:self.loop.thread.join(6)
        self.loop.advisory._auto_pool.shutdown(wait=True,cancel_futures=False)

class RuntimeRouter:
    def __init__(self,runtime,root):self.runtime=runtime;self.root=Path(root)
    def accepts_post(self,path):return path=='/api/system/runtime/control'
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/assets/runtime-center.js':return 200,Path(__file__).with_name('static').joinpath('runtime-center.js').read_bytes(),'text/javascript; charset=utf-8'
        if path not in ('/api/system/runtime','/api/system/runtime/control'):return None
        from app.system.runtime_control import control_request
        if method=='GET':
            try:value=control_request(self.root,{'action':'status'})
            except (OSError,ValueError):value={'status':'SUPERVISOR_OFFLINE','desired':self.runtime.state.read(),'services':{}}
            return 200,{**value,'web_runtime':self.runtime.status()},None
        if method=='POST':
            try:return 202,control_request(self.root,payload),None
            except (OSError,ValueError) as error:return 409,{'error':str(error),'message':'运行管理者暂不可用；请使用本机后台控制入口。'},None
