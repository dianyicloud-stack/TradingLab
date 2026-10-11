"""Actual HTTP boundary diagnostics and optional shared validation allowance."""
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from contextlib import closing


class RequestGuardError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)


def sanitized_error(body):
    error=body.get('error',{}) if isinstance(body,dict) else {}
    if not isinstance(error,dict):error={}
    message=str(error.get('message',''))
    lower=message.lower()
    reason=('INPUT_LENGTH_REJECTED' if any(k in lower for k in ('context length','too long','too large','maximum context','token limit','length limit')) else
            'REQUEST_PARAMETER_REJECTED' if any(k in lower for k in ('parameter','invalid','unsupported','schema')) else 'UPSTREAM_REJECTION')
    # A provider may echo arbitrary input in its error. Preserve only known
    # diagnostic vocabulary, numbers and punctuation; everything else is hidden.
    allowed=set('the this a an is are was were be for of and or in on at to by with not no only must maximum minimum max min context length input output tokens token requested request message messages model models parameter parameters invalid unsupported support supported too long large exceeded exceed limit exceeds response responses schema format required expected string integer value budget total reduce your please has have you but got allowed does can should characters character size exceeds max_output_tokens reasoning effort text type name None null deepseek-v4-pro'.lower().split())
    def word(m):
        s=m.group();return s if s.lower() in allowed or s.isdecimal() else '[redacted]'
    safe=re.sub(r'[\w./:@+\-]+',word,message)
    safe=re.sub(r'(?:\[redacted\][\s,]*){2,}','[redacted] ',safe)
    out={'reason':reason,'message_excerpt':safe.encode()[:2048].decode('utf-8','ignore')}
    for key in ('code','type','param'):
        value=error.get(key)
        if value is None:out[key]=None
        elif re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.\[\]-]{0,79}',str(value)) and not str(value).startswith(('sk-','Bearer')):out[key]=value
        else:out[key]='[redacted]'
    return out


class RequestGuard:
    def __init__(self,metadata,*,budget_path=None,limit=3,recorder=None,endpoint=None):
        self.metadata=metadata;self.budget_path=budget_path;self.limit=limit;self.records=[];self.recorder=recorder
        self.rejected=set()
        self.endpoint=endpoint or ('api.deepseek.com','/responses')

    def before(self,request):
        if request.method!='POST' or (request.url.host,request.url.path)!=self.endpoint:
            raise RequestGuardError('UNEXPECTED_PROVIDER_ENDPOINT')
        raw=request.content;body=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
        from engines.live.evidence import estimate,encoded
        semantic={**body,'input':json.loads(body['input'])}
        count=estimate(encoded(semantic))
        # DeepSeek V4 Pro: 1M context; null output limit reserves its documented
        # maximum 384K. Byte bound is deliberately stricter than token estimate.
        output=body.get('max_output_tokens') or self.metadata.get('model_max_output_tokens',393216)
        context=self.metadata.get('model_context_tokens',1048576)
        if len(self.records)>=3:raise RequestGuardError('HTTP_ATTEMPT_BUDGET_EXHAUSTED')
        if count>self.metadata['target_input_tokens'] or len(raw)+output+16384>context:
            raise RequestGuardError('INPUT_BUDGET')
        if sha in self.rejected:raise RequestGuardError('REPEATED_REJECTED_REQUEST')
        number=None
        if self.budget_path:
            with closing(sqlite3.connect(self.budget_path,timeout=10)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS attempts(n INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,status INTEGER,created_at TEXT NOT NULL)')
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT count(*) FROM attempts').fetchone()[0]>=self.limit:raise RequestGuardError('HTTP_ATTEMPT_BUDGET_EXHAUSTED')
                if db.execute('SELECT 1 FROM attempts WHERE sha256=? AND status=400',(sha,)).fetchone():raise RequestGuardError('REPEATED_REJECTED_REQUEST')
                number=db.execute('INSERT INTO attempts(sha256,created_at) VALUES(?,?)',(sha,datetime.now(timezone.utc).isoformat())).lastrowid
        record={'request_body_sha256':sha,'request_body_bytes':len(raw),'estimated_input_tokens':count,
            'token_count_method':self.metadata['token_count_method'],'input_builder_version':self.metadata['input_builder_version'],
            'endpoint':str(request.url),'method':request.method,'attempt':len(self.records)+1,'validation_attempt':number,
            'request_body':raw.decode(),'created_at':datetime.now(timezone.utc).isoformat()}
        if self.recorder:self.recorder(record)
        self.records.append(record)

    def after(self,response):
        record=self.records[-1];record['upstream_http_status']=response.status_code
        request_id=response.headers.get('x-request-id') or response.headers.get('request-id')
        record['upstream_request_id']=request_id if request_id and re.fullmatch(r'[\w-]{1,160}',request_id) else None
        if response.status_code>=400:
            response.read()
            try:record['upstream_error']=sanitized_error(response.json())
            except (ValueError,TypeError):record['upstream_error']={'reason':'NON_JSON_UPSTREAM_ERROR'}
        if response.status_code==400:self.rejected.add(record['request_body_sha256'])
        if self.budget_path and record['validation_attempt']:
            with closing(sqlite3.connect(self.budget_path)) as db, db:db.execute('UPDATE attempts SET status=? WHERE n=?',(response.status_code,record['validation_attempt']))

    def diagnostics(self):
        return {'provider_attempt_count':len(self.records),'http_attempts':[{k:v for k,v in r.items() if k!='request_body'} for r in self.records]}
