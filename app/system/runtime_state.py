"""System-owned desired state. No market or account persistence access."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json, os, threading, time, uuid
from adapters.runtime_lease import runtime_lease

def stamp(): return datetime.now(timezone.utc).isoformat()

def read_json(path):
    end=time.monotonic()+.5
    while True:
        try:return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if time.monotonic()>=end:raise
            time.sleep(.01)

def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        end=time.monotonic()+2
        while True:
            try:temp.replace(path);break
            except PermissionError:
                if time.monotonic()>=end:raise
                time.sleep(.01) # Windows readers may briefly deny replacement; never alter ACLs.
    finally:
        if temp.exists():temp.unlink()

class RuntimeState:
    def __init__(self, root,clock=stamp):
        self.root=Path(root).resolve();self.path=self.root/'system/runtime-control.json'
        self.lock=threading.RLock();self.clock=clock
    def read(self):
        if self.path.exists():return read_json(self.path)
        return {'schema_version':1,'revision':0,'web':'STOPPED','agent':'STOPPED',
            'listener':'DISABLED','listener_revision':0,'migration':'UNKNOWN_LISTENER_INTENT_DISABLED',
            'startup':'MANUAL','updated_at':None}
    @contextmanager
    def transaction(self):
        with self.lock:
            end=time.monotonic()+5
            while True:
                lease=runtime_lease(self.root/'runtime/control-state-lease')
                try:lease.__enter__();break
                except RuntimeError:
                    if time.monotonic()>=end:raise ValueError('CONTROL_STATE_BUSY')
                    time.sleep(.02)
            try:yield
            finally:lease.__exit__(None,None,None)
    def update(self, changes, expected=None):
        if set(changes)-{'web','agent','listener','startup'}:raise ValueError('INVALID_CONTROL_FIELD')
        for key,value in changes.items():
            allowed=('ENABLED','DISABLED') if key=='listener' else ('MANUAL','LOGON','BOOT') if key=='startup' else ('RUNNING','STOPPED')
            if value not in allowed:raise ValueError('INVALID_CONTROL_STATE')
        with self.transaction():
            old=self.read()
            if expected is not None and expected!=old['revision']:raise ValueError('CONTROL_VERSION_CONFLICT')
            if all(old[k]==v for k,v in changes.items()) and self.path.exists():return old
            value={**old,**changes,'revision':old['revision']+1,'updated_at':stamp()}
            if 'listener' in changes and old['listener']!=changes['listener']:
                value['listener_revision']=value['revision'];value['migration']='EXPLICIT_USER_INTENT'
                if changes['listener']=='ENABLED':value['listener_enabled_at']=self.clock()
            atomic(self.path,value);return value
