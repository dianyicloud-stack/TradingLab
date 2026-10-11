"""Live-owned last successful aggregate. Polling clients do not scan sources."""
from copy import deepcopy
from pathlib import Path
from threading import Thread,Event,Lock
from datetime import datetime,timezone
import json,time
from shared.logging.timing import RequestTimings,stage

class LiveReadModel:
    def __init__(self,path,collect):
        self.path=Path(path);self.collect=collect;self.stop_event=Event();self.lock=Lock();self.value=None;self.error=None;self.thread=None
        try:self.value=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        if self.value:self.value['read_model']['refresh_state']='RESTORED_WAITING_REFRESH'
    def start(self):
        if self.thread:return
        def run():
            while not self.stop_event.is_set():
                started=time.monotonic()
                try:
                    with RequestTimings.configured().request('/internal/read-model/'+self.path.parent.name,'COLLECT'):
                        with stage('read_model_collect'):value=self.collect()
                    if value.get('fact_error'):raise ValueError(value['fact_error']['message'])
                    value['read_model']={'collected_at':datetime.now(timezone.utc).isoformat(),'refresh_state':'CURRENT','collection_seconds':time.monotonic()-started}
                    self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(self.path)
                    with self.lock:self.value=value;self.error=None
                except Exception as e:
                    with self.lock:self.error=str(e)
                self.stop_event.wait(max(.1,2.5-(time.monotonic()-started)))
        self.thread=Thread(target=run,daemon=True,name='live-read-model');self.thread.start()
    def read(self):
        with self.lock:value=deepcopy(self.value);error=self.error
        if value is None:return {'status':'INITIAL_LOADING','message':error or '正在整理首次市场数据；尚无成功读模型。'}
        if error:value['read_model'].update(refresh_state='REFRESH_FAILED',error=error)
        return value
    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(10)
