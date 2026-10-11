"""Opt-in bounded analysis trace. Only allowlisted identifiers and status fields."""
from collections import deque
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
import json,logging,os


class AnalysisDiagnostics:
    fields=frozenset(('task_id','symbol','stage','state','requested_at','cutoff','completed_at',
                      'error_code','retryable','http_status','opinion_id','input_id','occurred_at'))
    def __init__(self,path=None,enabled=False):
        self.enabled=enabled or bool(path);self.rows=deque(maxlen=128);self.lock=Lock();self.handler=None
        if path:
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            self.handler=RotatingFileHandler(path,maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    @classmethod
    @lru_cache(maxsize=1)
    def configured(cls):return cls(os.environ.get('TRADING_LAB_ANALYSIS_DIAGNOSTICS'))
    def record(self,**value):
        if not self.enabled:return
        row={key:item for key,item in value.items() if key in self.fields and (item is None or type(item) in (str,int,bool))}
        with self.lock:
            self.rows.append(row)
            if self.handler:
                try:self.handler.emit(logging.LogRecord('analysis',logging.INFO,'',0,json.dumps(row),(),None))
                except OSError:pass  # Diagnostics cannot affect an analysis result.
    def close(self):
        if self.handler:self.handler.close()
