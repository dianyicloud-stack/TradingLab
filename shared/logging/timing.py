"""Opt-in, bounded operational timings. Never record payloads, SQL or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from collections import deque
from datetime import datetime, timezone
from functools import wraps, lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock, active_count
import json, logging, os, time, uuid

_current=ContextVar('request_timing',default=None)

@contextmanager
def stage(name):
    row=_current.get()
    if row is None:
        yield
        return
    start=time.perf_counter()
    try:yield
    finally:
        item=row['stages'].setdefault(name,{'count':0,'ms':0})
        item['count']+=1;item['ms']+=round((time.perf_counter()-start)*1000,3)

@contextmanager
def measured_lock(lock):
    with stage('source_lock_wait'):lock.acquire()
    try:yield
    finally:lock.release()

class RequestTimings:
    def __init__(self,path=None,enabled=False):
        self.enabled=enabled or bool(path);self.lock=Lock();self.active=0;self.peak=0;self.completed=0;self.rows=deque(maxlen=128);self.handler=None
        if path:
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            self.handler=RotatingFileHandler(path,maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    @classmethod
    @lru_cache(maxsize=1)
    def configured(cls):return cls(os.environ.get('TRADING_LAB_READ_TIMINGS'))
    @contextmanager
    def request(self,route,method):
        if not self.enabled:
            yield None
            return
        row={'request_id':uuid.uuid4().hex[:16],'route':route,'method':method,'entered_at':datetime.now(timezone.utc).isoformat(),'stages':{},'disconnected':False}
        start=time.perf_counter();token=_current.set(row)
        with self.lock:self.active+=1;self.peak=max(self.peak,self.active);row['active_at_entry']=self.active
        try:yield row
        finally:
            row.update(ended_at=datetime.now(timezone.utc).isoformat(),total_ms=round((time.perf_counter()-start)*1000,3),threads=active_count())
            with self.lock:
                self.active-=1;self.completed+=1;self.rows.append(row)
                if self.handler:self.handler.emit(logging.LogRecord('read_timing',logging.INFO,'',0,json.dumps(row),(),None))
            _current.reset(token)
    def snapshot(self):
        with self.lock:return {'active':self.active,'peak':self.peak,'completed':self.completed,'recent':list(self.rows)}
    def close(self):
        if self.handler:self.handler.close()

def timed_request(fn):
    @wraps(fn)
    def run(self,*args,**kwargs):
        # Query values can include identities; record route only, no request body.
        with self.server.performance.request(self.path.split('?',1)[0],self.command) as row:
            self._timing=row
            return fn(self,*args,**kwargs)
    return run
