"""Derived evidence validation against native rules; never invents market facts."""
from math import isfinite
from engines.live.native_health import instant

VERSION='native-event-evidence-1'
# Mirrors EVENT_DEFINITIONS and the evidence dependencies of trackerDeltaRows.
# It validates supporting facts; it does not recompute or upgrade native events.
NATIVE_EVENTS={'LOW_VOLUME_PULLBACK':'缩量回踩','NEW_HIGH':'新高','NEW_LOW':'新低',
 'VWAP_RECLAIM':'VWAP重新夺回','SUPPORT_RETEST':'支撑二次测试',
 'PRICE_EFFICIENCY_DECAY':'价格效率衰减','VOLUME_BREAKDOWN':'放量破位','ALPHA_DETERIORATE':'Alpha快速恶化'}
REQUIRED={
 'NEW_HIGH':('price','high'), 'NEW_LOW':('price','low'),
 'LOW_VOLUME_PULLBACK':('price','low','intervalChange','volumeRatio','volumeRatioSample','cumulativeVolume','deltaVolume'),
 'VOLUME_BREAKDOWN':('price','low','intervalChange','volumeRatio','volumeRatioSample','cumulativeVolume','deltaVolume'),
 'VWAP_RECLAIM':('price','vwap','vwapGap'),
 'SUPPORT_RETEST':('price','low'),
 'PRICE_EFFICIENCY_DECAY':('price','priceEfficiency','deltaTurnover'),
 'ALPHA_DETERIORATE':('price','alpha','stockChange','boardChange')}

def numeric(value):return type(value) in (int,float) and isfinite(value)

def validate(event,observations,session):
    kind=event.get('type') or event.get('event_type')
    result={'version':VERSION,'basis':'DERIVED_NATIVE_RULE_REQUIREMENTS','event_id':event.get('event_id') or event.get('trigger_id'),
            'event_type':kind,'status':'INSUFFICIENT','missing':[],'optional_missing':[],'evidence_refs':[]}
    if event.get('trigger_id'):
        ev=event.get('evidence',{})
        result['missing']=[k for k in ('before_id','after_id','window_start','window_end') if not ev.get(k)]
        result['missing'] += [k for k in ('before_price','after_price') if not numeric(ev.get(k)) or ev[k]<=0]
        result['status']='SUFFICIENT' if not result['missing'] else 'INSUFFICIENT';return result
    if kind not in REQUIRED:result['missing']=['UNSUPPORTED_NATIVE_EVENT_TYPE'];return result
    sid=session['tracking_session_id'];day=session.get('session_date') or session.get('market_date')
    if event.get('tracking_session_id')!=sid or event.get('symbol')!=session['symbol'] or event.get('session_date')!=day:
        result['missing']=['EVENT_IDENTITY_MISMATCH'];return result
    point=event.get('requested_time') or str(event.get('timestamp','')).split('T')[-1][:5]
    rows=[r for r in observations if r.get('source_owner')=='MARKET_DATA_AGENT' and r.get('source_format')=='V2A_NATIVE_EXPORT_V1'
          and r.get('tracking_session_id')==sid and r.get('symbol')==session['symbol'] and r.get('session_date')==day]
    associated=[r for r in rows if r.get('native_rule_evidence',{}).get('requestedTime')==point]
    if not associated:result['missing']=['ASSOCIATED_OBSERVATION_MISSING'];return result
    row=max(associated,key=lambda r:(r.get('revision',0),r.get('exported_at','')));raw=row.get('native_rule_evidence',{})
    result['evidence_refs']=[{'record_id':row.get('record_id'),'sha256':row.get('native_sha256'),'available_at':row.get('available_at')}]
    missing=result['missing'];missing.extend(k for k in REQUIRED[kind] if not numeric(raw.get(k)))
    if numeric(raw.get('price')) and raw['price']<=0:missing.append('PRICE_INVALID')
    if 'volumeRatioSample' in REQUIRED[kind] and numeric(raw.get('volumeRatioSample')) and raw['volumeRatioSample']<1:missing.append('VOLUME_COMPARISON_MISSING')
    if row.get('quality_version') not in (None,VERSION):missing.append('QUALITY_VERSION_UNSUPPORTED')
    if row.get('quality') not in (None,'COMPLETE'):missing.append('SOURCE_QUALITY_NOT_COMPLETE')
    if not row.get('interval_complete'):missing.append('FORMAL_INTERVAL_MISSING')
    prior=[r for r in rows if r.get('native_rule_evidence',{}).get('requestedTime','')<point and not r.get('native_rule_evidence',{}).get('auctionPoint')]
    # Keep the latest revision of each prior observation, not multiple copies.
    unique={}
    for r in sorted(prior,key=lambda x:(x.get('revision',0),x.get('exported_at',''))):unique[r.get('observation_id') or r['record_id']]=r
    prior=sorted(unique.values(),key=lambda r:r['native_rule_evidence']['requestedTime'])
    previous=prior[-1] if prior else None
    dependencies={'NEW_HIGH':('high',),'NEW_LOW':('low',),'LOW_VOLUME_PULLBACK':('low',),
      'VOLUME_BREAKDOWN':('low',),'VWAP_RECLAIM':('vwapGap',),
      'SUPPORT_RETEST':('low',),'PRICE_EFFICIENCY_DECAY':('priceEfficiency',),'ALPHA_DETERIORATE':('alpha','stockChange','boardChange')}
    if not previous:missing.append('COMPARISON_OBSERVATION_MISSING')
    else:
        compared=prior if kind in ('NEW_HIGH','NEW_LOW','SUPPORT_RETEST','VOLUME_BREAKDOWN','LOW_VOLUME_PULLBACK') else [previous]
        for before in compared:
            evidence=before['native_rule_evidence']
            missing.extend('previous.'+k for k in dependencies[kind] if not numeric(evidence.get(k)))
            result['evidence_refs'].append({'record_id':before.get('record_id'),'sha256':before.get('native_sha256'),'available_at':before.get('available_at')})
        if kind in ('LOW_VOLUME_PULLBACK','VOLUME_BREAKDOWN'):
            # Range comparison uses earlier lows; interval price/volume uses
            # only the native rule's recorded comparisonTime, not every row.
            comparison=next((r for r in reversed(rows) if r['native_rule_evidence'].get('requestedTime')==raw.get('comparisonTime')),None)
            if comparison is None:missing.append('INTERVAL_COMPARISON_OBSERVATION_MISSING')
            else:
                missing.extend('comparison.'+k for k in ('price','cumulativeVolume') if not numeric(comparison['native_rule_evidence'].get(k)))
                result['evidence_refs'].append({'record_id':comparison.get('record_id'),'sha256':comparison.get('native_sha256'),'available_at':comparison.get('available_at')})
        if kind=='SUPPORT_RETEST' and len(prior)<3:missing.append('THREE_COMPARISON_OBSERVATIONS_REQUIRED')
        if kind=='VWAP_RECLAIM' and (raw.get('amountTrusted') is not True or previous['native_rule_evidence'].get('amountTrusted') is not True):missing.append('AMOUNT_TRUST_NOT_CONFIRMED')
        if kind=='ALPHA_DETERIORATE' and (raw.get('boardPending') is not False or previous['native_rule_evidence'].get('boardPending') is not False):missing.append('INDUSTRY_COMPARISON_PENDING')
    for key in ('boardMedianChange','boardMedianTotal','volumeRatio'):
        if raw.get(key) is None:result['optional_missing'].append(key)
    ev=event.get('evidence',{})
    for key in REQUIRED[kind]:
        if key in ev and numeric(ev[key]) and numeric(raw.get(key)) and abs(ev[key]-raw[key])>1e-8*max(1,abs(ev[key])):missing.append('EVENT_OBSERVATION_MISMATCH:'+key)
    result['missing']=sorted(set(missing));result['status']='SUFFICIENT' if not missing else 'INSUFFICIENT'
    return result

def evaluate(frozen,events):
    session={**frozen.get('source_session',{}),'tracking_session_id':frozen['tracking_session_id'],
             'symbol':frozen['symbol'],'session_date':frozen['session_date']}
    observations=frozen.get('quality_observations',frozen['context_evidence']['observations'])
    return [validate(e,observations,session) for e in events]
