"""Explicit one-generation verification. No Live/Account/Telegram capability."""
from datetime import datetime,timezone
from uuid import uuid4
from pathlib import Path
from tempfile import TemporaryDirectory
from adapters.ai.capabilities import freeze,fingerprint
from engines.history.service import PROMPT,SCHEMA
from contracts.live.bridge import BridgeError

def verify(provider,configuration):
    stamp=datetime.now(timezone.utc).isoformat();identity='VERIFY-'+uuid4().hex
    config=freeze({**configuration,'http_attempt_limit':1},PROMPT,SCHEMA)
    # Explicitly synthetic, completed historical facts: verification cannot become a trade.
    day='2026-09-23';cutoff=day+'T15:00:00+08:00'
    frozen={'mode':'HISTORY_EOD','input_id':identity,'symbol':'TEST_ONLY','end_date':day,'visible_through':cutoff,
        'period':'DAY','volume_period':'DAY','portfolio_context':None,'model_config':config,
        'source':'SYNTHETIC_PROVIDER_VERIFICATION','bars':[{'date':day,'open':10,'high':11,'low':9.8,'close':10.5,
            'volume':100000,'amount':None,'complete':True,'available_at':cutoff,'members':[{'date':day}]}],
        'volume_context':{'period':'DAY','status':'INSUFFICIENT_SAMPLES','target_volume':100000,
            'historical_average':None,'ratio':None,'actual_samples':0,'requested_samples':20,'samples':[],
            'complete':True,'target_trading_days':1,'target_end':day},
        'quality':{'synthetic':True,'missing':['historical_volume_samples','amount']}}
    frozen['input_hash']=fingerprint(frozen)
    try:
        with TemporaryDirectory(prefix='tradinglab-model-check-') as temp:
            response=provider.analyze_history(frozen,config['provider'],config['model'],config['reasoning_effort'],
                PROMPT,SCHEMA,Path(temp)/'requests',Path(temp)/'attempts.db')
        return {'status':'PASS','message':'结构化输出验证通过（合成历史证据，不涉及账户）。','checked_at':stamp,
            'model_config':config,'attempts':response.get('provider_attempt_count'),
            'usage':response.get('usage'),'latency_ms':response.get('latency_ms'),
            'upstream_request_id':response.get('upstream_request_id'),'analysis':response['analysis']}
    except BridgeError as e:
        failure=getattr(e,'failure_metadata',{})
        return {'status':'FAILED','checked_at':stamp,'model_config':config,'attempts':failure.get('provider_attempt_count',0),
            'error':failure.get('error_code',e.code),'message':str(e),'http_status':failure.get('http_status')}
