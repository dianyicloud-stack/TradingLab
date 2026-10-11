"""Token-safe, one-way Telegram transport. No Telegram inbound API."""
from dataclasses import dataclass,field
from pathlib import Path
import json,os,re,socket,urllib.request,urllib.error
from dotenv import dotenv_values

@dataclass
class TelegramConfig:
    enabled: bool=False
    token: str=field(default='',repr=False)
    chat_id: str=field(default='',repr=False)
    proxy: str=field(default='',repr=False)
    env_path: str=''
    allowed_chat_id: str=field(default='',repr=False)
    namespace: str='USER'
    @property
    def state(self):
        if self.namespace!='USER' or not self.enabled:return 'DISABLED'
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}',self.token) or any(s in self.token.lower() for s in ('placeholder','your_token','your_bot')):return 'NO_TOKEN'
        if not re.fullmatch(r'[1-9][0-9]{0,15}',self.allowed_chat_id) or self.chat_id!=self.allowed_chat_id:return 'INVALID_CHAT'
        return 'READY'

def load_config(project,namespace='USER',environment=None):
    path=Path(project).resolve()/'.env'
    if namespace!='USER':return TelegramConfig(env_path=str(path),namespace=namespace)
    env={**dotenv_values(path),**(os.environ if environment is None else environment)}
    # Local operator authorization only: neither HTTP payloads nor environment
    # overrides may supply this value. Reuse dotenv without interpolation.
    authorization=path.with_name('.env.telegram')
    allowed=''
    try:
        if authorization.is_file() and not authorization.is_symlink():
            info=authorization.stat(follow_symlinks=False)
            if info.st_nlink==1 and not (getattr(info,'st_file_attributes',0)&1024):
                allowed=str(dotenv_values(authorization,interpolate=False).get('TELEGRAM_ALLOWED_CHAT_ID') or '')
    except OSError:
        pass # Missing/unreadable authorization fails closed below; never print it.
    return TelegramConfig(str(env.get('TELEGRAM_NOTIFICATIONS_ENABLED','')).lower()=='true',
        env.get('TELEGRAM_BOT_TOKEN') or '',str(env.get('TELEGRAM_CHAT_ID') or ''),
        env.get('TELEGRAM_PROXY_URL') or '',str(path),allowed_chat_id=allowed,namespace=namespace)

class TelegramSender:
    def __init__(self,config,opener=None):
        self.config=config
        self.opener=opener or urllib.request.build_opener(*([urllib.request.ProxyHandler({'https':config.proxy})] if config.proxy else []))
    def send(self,text):
        if self.config.state!='READY':return {'state':self.config.state}
        if len(text.encode('utf-16-le'))//2>4096:return {'state':'INVALID_MESSAGE'}
        req=urllib.request.Request('https://api.telegram.org/bot'+self.config.token+'/sendMessage',
            data=json.dumps({'chat_id':self.config.chat_id,'text':text},ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(req,timeout=12) as response:result=json.loads(response.read(65536))
        except urllib.error.HTTPError as error:
            try:result=json.loads(error.read(65536))
            except Exception:result={'error_code':error.code}
            result['ok']=False;result.setdefault('error_code',error.code)
        except (OSError,ValueError,socket.timeout):
            # A lost response may follow delivery. Never replay this part automatically.
            return {'state':'UNKNOWN'}
        if not isinstance(result,dict):return {'state':'UNKNOWN'}
        message=(result.get('result') or {}).get('message_id') if isinstance(result.get('result',{}),dict) else None
        if result.get('ok') is True and type(message) is int and message>0:return {'state':'SENT','message_id':message}
        code=result.get('error_code')
        if code==429:
            try:delay=max(1,int(result.get('parameters',{}).get('retry_after',60)))
            except (ValueError,TypeError):delay=60
            return {'state':'RETRY','retry_after':delay}
        return {'state':{401:'AUTH_ERROR',403:'FORBIDDEN',400:'INVALID_MESSAGE'}.get(code,'UNKNOWN')}
