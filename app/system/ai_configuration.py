"""System owns default AI selection. Resolution has no market/account side effects."""
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
import json,sqlite3,re
from threading import Lock
from adapters.ai.capabilities import resolve,MODELS,freeze
from contracts.live.bridge import BridgeError

FIELDS=('provider','model','reasoning_effort','max_output_tokens')

class AIConfiguration:
    def __init__(self,store,provider,existing):
        store.ensure();self.path=store.path('ai-configuration.db');self.provider=provider;self.verification_lock=Lock()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,body TEXT NOT NULL)')
            if not db.execute("SELECT 1 FROM state WHERE key='default'").fetchone():
                value={k:existing[k] for k in FIELDS if k in existing}
                db.execute('INSERT INTO state VALUES(?,?)',('default',json.dumps({'selection':value,'revision':1,'origin':'MIGRATED_EFFECTIVE_LIVE'})))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=5)
        try:
            with db:yield db
        finally:db.close()
    def read(self,key):
        with self.db() as db:row=db.execute('SELECT body FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def resolve(self,override=None):
        if override is not None and (not isinstance(override,dict) or set(override)-set(FIELDS)):raise BridgeError('INVALID_MODEL_SELECTION','模型选择包含不支持的字段。',400)
        saved=self.read('default');selection={**saved['selection'],**{k:v for k,v in (override or {}).items() if k in FIELDS}}
        if override and override.get('provider',selection['provider'])!=saved['selection'].get('provider') and 'max_output_tokens' not in override:selection.pop('max_output_tokens',None)
        value=resolve(selection,self.provider.connections())
        value.update(config_revision=saved['revision'],configuration_origin='OVERRIDE' if override else 'SYSTEM_DEFAULT')
        return value
    def status(self):
        saved=self.read('default')
        try:effective=self.resolve();error=None
        except BridgeError as e:effective=saved['selection'];error=str(e)
        return {'default':effective,'selection':saved['selection'],'revision':saved['revision'],'origin':saved['origin'],
            'catalog':self.provider.catalog(),'error':error,'draft':self.read('draft'),
            'remote_models':self.read('remote_models'),'verification':self.read('verification'),
            'env_path':str((self.provider.root/'.env').resolve()),
            'credential_priority':'进程环境优先于项目根 .env；密钥修改后重启 Web。模型选择由 System 持久设置决定。'}
    def save(self,payload):
        if set(payload)-set(FIELDS)-{'draft'}:raise BridgeError('INVALID_AI_CONFIGURATION','包含不支持的配置字段。',400)
        if payload.get('draft'):
            p=payload.get('provider');m=payload.get('model','')
            if p not in MODELS or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',m):raise BridgeError('INVALID_MODEL_ID','模型标识无效。',400)
            value={k:v for k,v in payload.items() if k in FIELDS};value['status']='UNKNOWN_CAPABILITY'
            with self.db() as db:db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('draft',json.dumps(value)))
        else:
            # Validate and commit against the same serialized default revision.
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                old=json.loads(db.execute("SELECT body FROM state WHERE key='default'").fetchone()[0])
                selection={**old['selection'],**payload}
                # Output budget follows provider's server configuration when switching providers.
                if payload.get('provider',selection['provider'])!=old['selection'].get('provider') and 'max_output_tokens' not in payload:selection.pop('max_output_tokens',None)
                new=resolve(selection,self.provider.connections());prior=resolve(old['selection'],self.provider.connections())
                row={'selection':selection,'revision':old['revision']+int(new['semantic_id']!=prior['semantic_id']),'origin':'SYSTEM'}
                db.execute("UPDATE state SET body=? WHERE key='default'",(json.dumps(row),))
        return self.status()
    def refresh_models(self,provider):
        result=self.provider.list_models(provider)
        cached=self.read('remote_models') or {};cached[provider]=result
        with self.db() as db:db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('remote_models',json.dumps(cached)))
        return result
    def verify(self,selection):
        from adapters.ai.verification import verify
        if not self.verification_lock.acquire(False):raise BridgeError('VERIFICATION_BUSY','已有模型验证正在进行。',429)
        try:
            result=verify(self.provider,self.resolve(selection))
            with self.db() as db:db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('verification',json.dumps(result)))
            return result
        finally:self.verification_lock.release()

class AIConfigurationRouter:
    def __init__(self,service):self.service=service
    def accepts_put(self,path):return path=='/api/system/ai'
    def accepts_post(self,path):return path in ('/api/system/ai/models/refresh','/api/system/ai/verify')
    def route(self,method,path,payload=None):
        if method=='GET' and path=='/assets/ai-settings.js':return 200,Path(__file__).with_name('static').joinpath('ai-settings.js').read_bytes(),'text/javascript; charset=utf-8'
        if not path.startswith('/api/system/ai'):return None
        try:
            if method=='GET' and path=='/api/system/ai':return 200,self.service.status(),None
            if method=='PUT' and path=='/api/system/ai':return 200,self.service.save(payload or {}),None
            if method=='POST' and path=='/api/system/ai/models/refresh':return 200,self.service.refresh_models((payload or {}).get('provider')),None
            if method=='POST' and path=='/api/system/ai/verify':
                if (payload or {}).get('confirm_cost') is not True:raise BridgeError('CONFIRM_VERIFICATION_COST','请明确确认验证可能产生 API 费用。',400)
                return 200,self.service.verify((payload or {}).get('selection',{})),None
        except BridgeError as e:return e.http_status,{'error':e.code,'message':str(e)},None
        return 404,{'error':'NOT_FOUND'},None
