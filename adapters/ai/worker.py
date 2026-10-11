"""Authorized daily analysis using the frozen provider, in an isolated -I -B process."""
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import time


def safe_exception_details(error):
    """Keep transport shape and attempt count, never provider text or response data."""
    details={}
    records=getattr(error,'usage_records',None)
    if isinstance(records,list):details['provider_attempt_count']=len(records)
    cause=error.__cause__
    if cause is not None:
        kind=type(cause).__name__
        if kind in ('BadRequestError','NotFoundError','AuthenticationError','PermissionDeniedError',
                    'RateLimitError','InternalServerError','APIStatusError','APITimeoutError',
                    'APIConnectionError'):
            details['transport_exception_type']=kind
    return details


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(sys.argv[1]).resolve()
    legacy = root / 'legacy'
    sys.dont_write_bytecode = True
    logging.disable(logging.CRITICAL)
    request = json.load(sys.stdin)
    sys.path.insert(0,str(root))
    from adapters.ai.request_guard import RequestGuard,RequestGuardError
    observer=None
    def guard(event, args):
        paths = []
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
                paths = [path]
        elif event in {'os.remove','os.rmdir','os.mkdir','os.chmod','os.utime'}:
            paths = [args[0]]
        elif event in {'os.rename','os.link','os.symlink'}:
            paths = args[:2]
        for path in paths:
            if isinstance(path,(str,bytes,os.PathLike)) and Path(os.fsdecode(path)).resolve().is_relative_to(legacy):
                raise PermissionError('Legacy write denied')
    sys.addaudithook(guard)
    started = time.perf_counter()
    provider_name=request.get('provider','deepseek')
    result = {'status':'PROVIDER_ERROR','provider':provider_name,'model':request.get('model'),'failure_stage':'CONFIGURATION','provider_invoked':False}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            from adapters.ai.config import ConfigManager
            from adapters.ai.providers import build_provider
            import jsonschema
            from dotenv import load_dotenv
            load_dotenv(root/'.env',override=False)
            from adapters.ai.capabilities import resolve,ENDPOINTS,KEYS
            frozen=request.get('model_config')
            if frozen:
                # Frozen server-owned connection is validated without re-reading mutable model settings.
                config=resolve(frozen,{provider_name:frozen})
                if config['semantic_id']!=frozen.get('semantic_id'):
                    raise ValueError('frozen configuration identity mismatch')
            else:
                config=ConfigManager(root,root/'config/ai.yaml').provider_config(provider_name)
                config=resolve({'provider':provider_name,'model':request.get('model') or config.get('model'),
                    'reasoning_effort':request['reasoning']},{provider_name:config})
            model=config['model']
            if not os.getenv(config['api_key_env'], '').strip():
                result.update(status='API_KEY_MISSING',retryable=False)
                raise ValueError('missing key')
            result.update(provider=provider_name,model=model)
            provider = build_provider(provider_name,config,prompt=request['prompt'],output_schema=request['schema'])
            if request.get('evidence_metadata'):
                recorder=None
                if request.get('request_store'):
                    from engines.live.provider_request_repository import ProviderRequestRepository
                    audit=ProviderRequestRepository(request['request_store'])
                    recorder=lambda row:audit.append(request['source_input_id'],'HTTP_REQUEST',{k:v for k,v in row.items() if k!='request_body'})
                observer=RequestGuard({**request['evidence_metadata'],'model_context_tokens':config['context_tokens'],'model_max_output_tokens':config['model_max_output_tokens']},budget_path=request.get('http_budget_path') or os.environ.get('TRADING_LAB_AI_HTTP_BUDGET'),recorder=recorder,
                    limit=config['http_attempt_limit'],endpoint=('api.openai.com','/v1/responses') if provider_name=='openai' else None)
                original_create=provider.client.responses.create
                def compact_create(**kwargs):
                    # Lossless JSON whitespace compaction before SDK serialization.
                    kwargs['input']=json.dumps(json.loads(kwargs['input']),ensure_ascii=False,separators=(',',':'))
                    return original_create(**kwargs)
                provider.client.responses.create=compact_create
                provider.client._client.event_hooks['request'].append(observer.before)
                provider.client._client.event_hooks['response'].append(observer.after)
            try:
                result.update(failure_stage='PROVIDER',provider_invoked=True)
                response = provider.analyze_event(request['handoff'])
                result['failure_stage']='SCHEMA'
                jsonschema.validate(response['analysis'],request['schema'])
                records = response.get('usage_records',[])
                if not any(r.get('success') for r in records):
                    raise ValueError('no success evidence')
                # Allowlisted scalar telemetry only. Never emit error bodies or environment/config.
                usage = [{k:v for k,v in r.items() if k in ('success','latency_ms','input_tokens','output_tokens','total_tokens','prompt_tokens','completion_tokens','reasoning_tokens','cached_input_tokens') and (v is None or type(v) in (int,float,bool))} for r in records]
                import re
                upstream=response.get('request_id')
                upstream=upstream if isinstance(upstream,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}',upstream) else None
                result.update(status='PASS',analysis=response['analysis'],usage=usage,schema='PASS',reasoning_effort=config['reasoning_effort'],effective_reasoning_effort=config['effective_reasoning_effort'],upstream_request_id=upstream)
            finally:
                provider.client.close()
        except Exception as error:
            code = str(getattr(error,'code',''))
            retryable=getattr(error,'retryable',None)
            result['retryable']=retryable if type(retryable) is bool else result.get('retryable')
            status=getattr(error,'status_code',None)
            if type(status) is int:result['http_status']=status
            # The frozen provider owns the exception and its message. Keep only
            # safe scalar diagnostics; never forward the response body or prompt.
            result.update(safe_exception_details(error))
            causes=[];cause=error
            while cause is not None and len(causes)<8:
                causes.append(cause);cause=cause.__cause__
            boundary=next((e for e in causes if isinstance(e,RequestGuardError)),None)
            if code in ('PROVIDER_REFUSAL','OUTPUT_TRUNCATED','API_KEY_MISSING','AUTH_FAILED','RATE_LIMITED','TIMEOUT','EMPTY_PROVIDER_RESPONSE','INVALID_RESPONSE','SCHEMA_VALIDATION_FAILED','MODEL_INVALID','CONFIG_ERROR','PROVIDER_DISABLED','PROVIDER_NOT_IMPLEMENTED'):
                result['status'] = code
            elif type(status) is int:result['status']='HTTP_ERROR'
            elif type(error).__name__ in ('ValidationError','SchemaError'):result['status']='SCHEMA_VALIDATION_FAILED';result['retryable']=True
            elif type(error).__name__ in ('APIConnectionError','ConnectError','ConnectionError') or type(error.__cause__).__name__ in ('APIConnectionError','ConnectError','ConnectionError'):
                result['status']='NETWORK_ERROR';result['retryable']=True
            if result.get('failure_stage')=='CONFIGURATION' and result['status']=='PROVIDER_ERROR':result.update(status='CONFIG_ERROR',retryable=False)
            if boundary:result.update(status=boundary.code,retryable=False,provider_invoked=bool(observer and observer.records))
    if observer:
        result.update(observer.diagnostics())
        if request.get('request_store'):
            audit.append(request['source_input_id'],'HTTP_OUTCOME',{k:v for k,v in result.items() if k!='analysis'})
    result['latency_ms'] = round((time.perf_counter()-started)*1000)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))


if __name__ == '__main__':
    main()
