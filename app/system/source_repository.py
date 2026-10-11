"""System fixed-source configuration with versioned, idempotent audit migration."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock
import hashlib,json,os,uuid
_path_locks={};_registry_lock=RLock()
def now():return datetime.now(timezone.utc).isoformat()
class SourceRepository:
    def __init__(self,root,defaults):
        self.path=Path(root)/'market-source.json';self.defaults=deepcopy(defaults)
        with _registry_lock:self.lock=_path_locks.setdefault(str(self.path.resolve()),RLock())
    def read(self):
        with self.lock:
            value=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'config':deepcopy(self.defaults),'operations':{}}
            if not isinstance(value.get('operations'),dict) or not isinstance(value.get('config'),dict):raise ValueError('SOURCE_CONFIGURATION_INVALID')
            original=value['config'];config={**self.defaults,**original}
            config['active_market_source']='MARKET_AGENT'
            config['source_generation']=original.get('source_generation') or str(uuid.uuid5(uuid.NAMESPACE_URL,str(self.path.resolve())))
            retired={k:config.pop(k) for k in ('v2a_workspace','pending_cutover','producer_guard') if k in config}
            value['config']=config
            value['migration_required']=bool(self.path.exists() and (original.get('source_schema_version')!=2 or retired or original.get('active_market_source')!='MARKET_AGENT'))
            return value
    def write(self,value):
        if value['config'].get('active_market_source')!='MARKET_AGENT' or any(k in value['config'] for k in ('v2a_workspace','producer_guard','pending_cutover')):raise ValueError('SOURCE_SWITCHING_RETIRED')
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp')
            payload=deepcopy(value);payload.pop('migration_required',None);payload['config']['source_schema_version']=2
            with temp.open('w',encoding='utf-8') as h:json.dump(payload,h,ensure_ascii=False,indent=2,allow_nan=False);h.flush();os.fsync(h.fileno())
            temp.replace(self.path)
    def migrate(self):
        """Called only by explicit startup/deployment, never by a read endpoint."""
        with self.lock:
            value=self.read()
            if self.path.exists() and not value['migration_required']:return value
            original=self.path.read_bytes() if self.path.exists() else None
            digest=hashlib.sha256(original).hexdigest() if original else None;backup=None
            if original:
                backup=self.path.parent/'source-history'/('pre-agent-only-'+digest+'.json');backup.parent.mkdir(parents=True,exist_ok=True)
                if backup.exists():
                    if backup.read_bytes()!=original:raise ValueError('SOURCE_MIGRATION_BACKUP_MISMATCH')
                else:
                    with backup.open('xb') as h:h.write(original);h.flush();os.fsync(h.fileno())
            value.setdefault('migrations',[]).append({'version':2,'at':now(),'before_sha256':digest,'backup':str(backup) if backup else None,'operation':'FIX_PRODUCTION_SOURCE_TO_MARKET_AGENT','settings_scope':'SOURCE_ONLY'})
            value['config'].update(source_schema_version=2,updated_at=now(),updated_by='source-migration-v2')
            self.write(value);return self.read()
