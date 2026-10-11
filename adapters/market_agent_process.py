"""System lifecycle adapter. Activation is explicit and separate from Live AI."""
from pathlib import Path
import json,os,subprocess,sys,time
from datetime import datetime,timezone
from threading import Thread,Event
from bridges.market_agent import AgentClient
from contracts.live.market_agent import AgentError

def validate_activation(project,root):
    project=Path(project).resolve();root=Path(root).resolve()
    if root.is_relative_to(project) or project.is_relative_to(root):raise AgentError('AGENT_DATA_ROOT_MUST_BE_SEPARATE')
    activation=root/'activation.json'
    if not activation.exists():return {'enabled':False,'status':'ACTIVATION_REQUIRED'}
    value=json.loads(activation.read_text(encoding='utf-8'))
    if value.get('schema_version')!='1.0' or value.get('source')!='USER':raise AgentError('AGENT_ACTIVATION_INVALID')
    if value.get('collection_enabled') is True and not value.get('approved_at'):raise AgentError('AGENT_ACTIVATION_APPROVAL_REQUIRED')
    return {'enabled':value.get('collection_enabled') is True,'status':'CONFIGURED'}

class AgentSupervisor:
    def __init__(self,project_root,data_root=None,source='USER',overrides=None):
        from adapters.source_configuration import source_configuration
        self.project=Path(project_root);self.data_root=Path(data_root or self.project/'data');self.source=source;self.overrides=overrides
        self.repo,self.config=source_configuration(self.project,self.data_root,source,overrides)
        self.root=Path(self.config['market_agent_root']);self.client=AgentClient(self.root,source=source)
        self.stop_event=Event();self.process=None;self.thread=None
    def configuration(self):
        from adapters.source_configuration import source_configuration
        self.repo,self.config=source_configuration(self.project,self.data_root,self.source,self.overrides)
        if not self.config['agent_auto_start']:return {'enabled':False,'status':'AUTO_START_DISABLED'}
        return validate_activation(self.project,self.root)
    def ensure(self):
        config=self.configuration()
        if not config['enabled']:return config
        from adapters.market_source_lifecycle import SourceLifecycle
        lifecycle=SourceLifecycle(self.project,self.config)
        value=lifecycle.start()
        if value['agent_state']!='RUNNING':value=lifecycle.collect()
        return {'enabled':True,'status':'CONNECTED','agent':value['agent_state']}
    def watch(self):
        def run():
            failures=0
            while not self.stop_event.wait(5):
                try:
                    config=self.configuration()
                    if not config['enabled']:continue
                    self.ensure();failures=0
                except (ValueError,OSError,AgentError):
                    failures+=1
                    if failures>3:return
        self.thread=Thread(target=run,name='market-agent-supervisor',daemon=True);self.thread.start()
    def close(self):self.stop_event.set()
