"""Transport adapter; the existing DeepSeek provider performs the API call."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from contracts.live.bridge import BridgeError


class ProviderTransport:
    def __init__(self, root):
        self.root = root

    def analyze(self, handoff, reasoning, policy, prompt, schema, *, provider='deepseek', model=None,advisory_diagnostics=False,request_store=None,http_budget_path=None):
        metadata=None;source_input_id=handoff.get('input_id');model_config=handoff.get('model_config')
        if advisory_diagnostics:
            from engines.live.evidence import build
            if handoff.get('mode')=='HISTORY_EOD':
                from engines.history.service import evidence as build
            original=handoff
            try:handoff,metadata=build(original,prompt,schema)
            except Exception as error:
                from contracts.live.bridge import BridgeError
                if isinstance(error,BridgeError):
                    error.failure_metadata={'stage':'INPUT','error_code':error.code,'provider_invoked':False,'provider_attempt_count':0,'retryable':False}
                    if getattr(error,'budget_diagnostics',None):error.failure_metadata['input_budget']=error.budget_diagnostics
                raise
            if request_store:
                from engines.live.provider_request_repository import ProviderRequestRepository
                audit=ProviderRequestRepository(request_store)
                audit.append(source_input_id,'PREPARED_METADATA',metadata)
        with tempfile.TemporaryDirectory(prefix='tradinglab-advisory-') as cwd:
            try:
                run = subprocess.run([sys.executable,'-I','-B',str(Path(__file__).with_name('worker.py')),str(self.root)],
                    input=json.dumps({'handoff':{**handoff,'action_policy':policy},'reasoning':reasoning,
                                      'prompt':prompt,'schema':schema,'provider':provider,'model':model,'model_config':model_config,
                                      'evidence_metadata':metadata,'request_store':str(request_store) if request_store else None,
                                      'source_input_id':source_input_id,'http_budget_path':str(http_budget_path) if http_budget_path else None},ensure_ascii=False),
                    capture_output=True,text=True,encoding='utf-8',cwd=cwd,timeout=240)
                result = json.loads(run.stdout)
            except subprocess.TimeoutExpired:
                result={'status':'TIMEOUT','failure_stage':'PROVIDER','retryable':True}
            except (subprocess.SubprocessError,OSError,ValueError):
                result = {'status':'PROVIDER_UNAVAILABLE'}
        if advisory_diagnostics and result.get('status')!='PASS':
            from contracts.live.advisory import AdvisoryProviderFailure
            status=result.get('status');http=result.get('http_status')
            code={'TIMEOUT':'PROVIDER_TIMEOUT','NETWORK_ERROR':'PROVIDER_NETWORK_ERROR','HTTP_ERROR':'PROVIDER_HTTP_ERROR',
                  'INVALID_RESPONSE':'PROVIDER_PARSE_ERROR','EMPTY_PROVIDER_RESPONSE':'PROVIDER_PARSE_ERROR',
                  'SCHEMA_VALIDATION_FAILED':'PROVIDER_SCHEMA_ERROR','PROVIDER_UNAVAILABLE':'PROVIDER_WORKER_UNAVAILABLE',
                  'AUTH_FAILED':'AUTH_FAILED','API_KEY_MISSING':'API_KEY_MISSING','MODEL_INVALID':'MODEL_INVALID',
                  'PROVIDER_REFUSAL':'PROVIDER_REFUSAL','OUTPUT_TRUNCATED':'OUTPUT_TRUNCATED','RATE_LIMITED':'PROVIDER_RATE_LIMITED','CONFIG_ERROR':'PROVIDER_CONFIGURATION_ERROR',
                  'PROVIDER_DISABLED':'PROVIDER_CONFIGURATION_ERROR','PROVIDER_NOT_IMPLEMENTED':'PROVIDER_CONFIGURATION_ERROR'}.get(status,'PROVIDER_ERROR_UNCLASSIFIED')
            failure={'stage':result.get('failure_stage','PROVIDER'),'error_code':code,'retryable':result.get('retryable'),
                     'http_status':http if type(http) is int else None,'provider_invoked':result.get('provider_invoked')}
            if result.get('status') in ('INPUT_BUDGET','HTTP_ATTEMPT_BUDGET_EXHAUSTED','REPEATED_REJECTED_REQUEST'):
                failure.update(error_code=result['status'],retryable=False)
            if code in ('PROVIDER_REFUSAL','OUTPUT_TRUNCATED'):
                failure['reason']={'PROVIDER_REFUSAL':'服务商拒绝生成本次分析，未保存意见。','OUTPUT_TRUNCATED':'输出达到上限或未完整结束；未保存意见，请检查输出预算。'}[code]
            if result.get('http_attempts'):
                failure['http_attempts']=result['http_attempts']
                last=result['http_attempts'][-1]
                failure['upstream_error']=last.get('upstream_error')
                if last.get('upstream_error'):failure['reason']=last['upstream_error']['reason']
            attempts=result.get('provider_attempt_count')
            if type(attempts) is int and 0<=attempts<=10:failure['provider_attempt_count']=attempts
            kind=result.get('transport_exception_type')
            if kind in ('BadRequestError','NotFoundError','AuthenticationError','PermissionDeniedError',
                        'RateLimitError','InternalServerError','APIStatusError','APITimeoutError',
                        'APIConnectionError'):failure['transport_exception_type']=kind
            raise AdvisoryProviderFailure(failure)
        if result.get('status') != 'PASS':raise BridgeError('PROVIDER_FAILED','AI调用失败；未保存不合格意见。',502)
        return result
