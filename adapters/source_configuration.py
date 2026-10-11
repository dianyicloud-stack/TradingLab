"""Single production source; old selectors never grant fallback capabilities."""
from pathlib import Path
import os,sys
from dotenv import dotenv_values
from app.system.source_repository import SourceRepository

def source_configuration(project,data_root,source='USER',overrides=None,environment=None):
    project=Path(project).resolve()
    env={**dotenv_values(project/'.env'),**(os.environ if environment is None else environment)} if source=='USER' else {}
    agent=project.parent/'TradingLabData'/'MarketDataAgent' if sys.platform=='win32' else Path('/var/lib/tradinglab/market-agent')
    defaults={'active_market_source':'MARKET_AGENT','market_agent_root':str(agent) if source=='USER' else str(Path(data_root).parent/'agent'),'agent_auto_start':False,'source':source}
    repo=SourceRepository(Path(data_root)/'system',defaults);value=repo.read();config=value['config']
    if config.get('source')!=source:raise ValueError('SOURCE_CONFIGURATION_INVALID')
    explicit={};deprecated=[]
    for name in ('TRADING_LAB_LIVE_SOURCE','TRADING_LAB_V2A_WORKSPACE','TRADING_LAB_V2A_EXPORT_NAMESPACE'):
        if name in env:deprecated.append(name)
    if env.get('TRADING_LAB_MARKET_AGENT_ROOT'):
        config['market_agent_root']=env['TRADING_LAB_MARKET_AGENT_ROOT'];explicit['market_agent_root']='ENVIRONMENT'
    for key,v in (overrides or {}).items():
        if key in ('active_market_source','v2a_workspace'):deprecated.append('override:'+key);continue
        if key!='market_agent_root':raise ValueError('SOURCE_OVERRIDE_INVALID')
        config[key]=v;explicit[key]='EXPLICIT'
    path=Path(config['market_agent_root']).expanduser()
    if not path.is_absolute():raise ValueError('SOURCE_PATH_MUST_BE_ABSOLUTE')
    config['market_agent_root']=str(path.resolve());config['overrides']=explicit;config['deprecated_ignored']=deprecated
    config['migration_required']=value.get('migration_required',False)
    return repo,config
