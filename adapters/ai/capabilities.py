"""Reviewed text-analysis capabilities; remote model names never grant capabilities."""
from copy import deepcopy
from hashlib import sha256
import json
from contracts.live.bridge import BridgeError

VERSION='provider-config-1'
ENDPOINTS={'deepseek':'https://api.deepseek.com','openai':'https://api.openai.com/v1'}
KEYS={'deepseek':'DEEPSEEK_API_KEY','openai':'OPENAI_API_KEY'}
MODELS={
    'deepseek':{m:{'reasoning_efforts':['none','low','high','max'],'context_tokens':1048576,'max_output_tokens':393216,
        'reasoning_mapping':{'none':'none','low':'low','high':'high','max':'max'}} for m in ('deepseek-v4-pro','deepseek-flash')},
    'openai':{m:{'reasoning_efforts':['none','low','medium','high','xhigh'],'context_tokens':400000,'max_output_tokens':128000,
        'reasoning_mapping':{x:x for x in ('none','low','medium','high','xhigh')}} for m in ('gpt-5.4-mini','gpt-5.4-mini-2026-03-17')},
}

def fingerprint(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def resolve(selection, connections):
    p=selection.get('provider');m=selection.get('model');effort=selection.get('reasoning_effort','none')
    cap=MODELS.get(p,{}).get(m)
    if not cap:raise BridgeError('MODEL_CAPABILITY_UNKNOWN','该模型能力尚未审核，只能保存草稿。',400)
    c=connections.get(p,{})
    if not c.get('enabled'):raise BridgeError('PROVIDER_DISABLED','服务商未启用。',400)
    if effort not in cap['reasoning_efforts']:raise BridgeError('MODEL_REASONING_UNSUPPORTED','该模型不支持所选推理强度。',400)
    endpoint=c.get('base_url',ENDPOINTS[p]).rstrip('/')
    if endpoint!=ENDPOINTS[p] or c.get('api_key_env',KEYS[p])!=KEYS[p]:
        raise BridgeError('PROVIDER_CONNECTION_INVALID','连接地址或密钥引用与服务商不匹配。',400)
    output=selection.get('max_output_tokens',c.get('max_output_tokens'))
    if p=='openai' and output is None:output=8192
    if output is not None and (type(output) is not int or not 1<=output<=cap['max_output_tokens']):
        raise BridgeError('INVALID_OUTPUT_BUDGET','输出预算超出模型允许范围。',400)
    value={'provider':p,'model':m,'api_mode':'responses','base_url':endpoint,'api_key_env':KEYS[p],
        'reasoning_effort':effort,'effective_reasoning_effort':cap['reasoning_mapping'][effort],
        'max_output_tokens':output,'context_tokens':cap['context_tokens'],'model_max_output_tokens':cap['max_output_tokens'],
        'timeout_seconds':float(c.get('timeout_seconds') or 90),'http_attempt_limit':min(3,max(1,int(selection.get('http_attempt_limit',3)))),
        'structured_outputs':True,'allow_json_fallback':False,'enabled':True,'capability_version':VERSION}
    semantic={k:v for k,v in value.items() if k not in ('reasoning_effort','api_key_env','timeout_seconds','http_attempt_limit','enabled')}
    value['semantic_id']=fingerprint(semantic)
    return value

def freeze(config,prompt,schema):
    value=deepcopy(config)
    value.update(prompt_version=fingerprint(prompt),schema_version=fingerprint(schema))
    value['analysis_signature']=fingerprint({k:value[k] for k in ('semantic_id','prompt_version','schema_version')})
    return value

def strict_schema(schema):
    """Optional fields become required nullable on the wire, never invented values."""
    if isinstance(schema,list):return [strict_schema(x) for x in schema]
    if not isinstance(schema,dict):return schema
    result={('anyOf' if k=='oneOf' else k):strict_schema(v) for k,v in schema.items() if k not in ('$schema','minLength','maxLength')}
    if result.get('type')=='object':
        required=set(schema.get('required',[]));props=result.get('properties',{})
        for k,v in list(props.items()):
            if k not in required:props[k]={'anyOf':[v,{'type':'null'}]}
        result.update(required=list(props),additionalProperties=False)
    return result

def restore_optional(value,schema):
    """Undo wire-only nulls for originally optional fields; validate original schema next."""
    if isinstance(value,dict):
        result={};props=schema.get('properties',{});required=schema.get('required',[])
        for k,v in value.items():
            if k in props and k not in required and v is None:continue
            result[k]=restore_optional(v,props.get(k,{}))
        # Union alternatives may contain object properties, choose by shape/type.
        if not props:
            for branch in schema.get('oneOf',schema.get('anyOf',[])):
                if branch.get('type')=='object':return restore_optional(value,branch)
        return result
    if isinstance(value,list):return [restore_optional(x,schema.get('items',{})) for x in value]
    return value

def check_response(response,records):
    from adapters.ai.errors import CoordinatorError
    def get(v,k,default=None):return v.get(k,default) if isinstance(v,dict) else getattr(v,k,default)
    code=None
    if get(response,'status') in ('incomplete','failed','cancelled'):
        code='OUTPUT_TRUNCATED' if get(response,'status')=='incomplete' else 'INVALID_RESPONSE'
    for item in get(response,'output',[]) or []:
        if get(item,'status')=='incomplete':code='OUTPUT_TRUNCATED'
        for part in get(item,'content',[]) or []:
            if get(part,'type')=='refusal':code='PROVIDER_REFUSAL'
    if code:
        if records:records[-1].update(success=False,error_type=code)
        raise CoordinatorError(code,'上游未返回完整可用的分析结果。',usage_records=records)
