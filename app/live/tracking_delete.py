"""Tracking deletion through injected owner contracts; no Agent file/DB access."""
import uuid
from contextlib import nullcontext
import json
from contracts.live.market_agent import AgentError


class LiveTrackingDeletion:
    def __init__(self,client,advisory,account_refs):
        self.client=client;self.advisory=advisory
        self.account_refs=account_refs

    def references(self,symbol,sessions):
        refs={s:[] for s in sessions}
        for opinion in self.advisory.opinions.tracking_references(symbol):
            sid=opinion['tracking_session_id']
            if sid in refs:refs[sid].append('OPINION:'+opinion['advisory_id'])
        broad=self.account_refs(symbol)
        for values in refs.values():values.extend(broad)
        return refs

    def filter_current(self,value):
        retired=self.advisory.runtime.retired_sessions()
        if not retired:return value
        value={**value,'sessions':[s for s in value.get('sessions',[]) if s.get('tracking_session_id') not in retired]}
        if 'facts' in value:value['facts']=[f for f in value['facts'] if f['payload'].get('tracking_session_id') not in retired]
        return value

    def delete(self,payload):
        symbol=payload.get('symbol','').lower();runtime=self.advisory.runtime
        source=self.client.query()
        if 'TRACKING_DELETE_V1' not in source.get('capabilities',[]):
            raise AgentError('AGENT_DELETE_UPGRADE_REQUIRED','当前 Agent 尚未加载安全删除接口。需单独获准加载 Agent 更新后执行；本次未删除或隐藏任何数据。')
        if payload.get('confirmation')!='DELETE_TRACKING_DATA':raise AgentError('DELETE_CONFIRMATION_REQUIRED')
        if payload.get('source')!=source['source']:raise AgentError('COMMAND_CONTEXT_INVALID')
        current=[s['tracking_session_id'] for s in source['sessions'] if s['symbol']==symbol]
        prior=runtime.deletion_intent(symbol)
        if prior and prior['status']=='PENDING':command=prior['payload']
        elif prior and prior['status']=='DELETED' and not current:return {'status':'DELETED','idempotent':True,'symbol':symbol}
        else:
            refs=self.references(symbol,current)
            query={'schema_version':'1.0','source':source['source'],'symbol':symbol,'action':'DELETE_PLAN','protected_references':refs}
            plan=self.client.command(query)
            command={**query,'action':'DELETE','command_id':str(uuid.uuid4()),'confirmation':'DELETE_TRACKING_DATA',
                'expected_version':source['version'],'plan_hash':plan['plan_hash']}
            if len(json.dumps(command).encode())>8192:raise AgentError('DELETE_REFERENCE_MANIFEST_TOO_LARGE')
            with getattr(self.advisory,"_locks_guard",nullcontext()):
                runtime.begin_tracking_deletion(symbol,current,command)
        try:result=self.client.command(command)
        except AgentError as error:
            # These owner rejections prove no commit occurred. Refresh the plan
            # once; unknown network outcomes retain the original id for recovery.
            if error.code not in ('VERSION_CONFLICT','DELETE_PLAN_CHANGED'):raise
            source=self.client.query();current=[s['tracking_session_id'] for s in source['sessions'] if s['symbol']==symbol]
            command={**command,'protected_references':self.references(symbol,current)}
            plan=self.client.command({**command,'action':'DELETE_PLAN'})
            command.update(expected_version=source['version'],plan_hash=plan['plan_hash'])
            if len(json.dumps(command).encode())>8192:raise AgentError('DELETE_REFERENCE_MANIFEST_TOO_LARGE')
            with getattr(self.advisory,'_locks_guard',nullcontext()):runtime.begin_tracking_deletion(symbol,current,command)
            result=self.client.command(command)
        runtime.finish_tracking_deletion(symbol)
        return result
