"""Live-owned time and reading DTOs; never market or account mutations."""
import hashlib
from shared.serialization import canonical
from engines.live.native_health import instant


def fingerprint(value):
    def stable(item):
        if isinstance(item,dict):
            return {k:stable(v) for k,v in item.items() if k not in (
                'updated_at','read_at','fetched_at','generated_at','age_seconds','quote_age_seconds','market_time',
                'unrealized_pnl','current_position_weight','weight','market_value','valuation')}
        if isinstance(item,list):return [stable(v) for v in item]
        return item
    return hashlib.sha256(canonical(stable(value)).encode()).hexdigest()


def model_key(settings):
    return {k:settings.get(k) for k in ('provider','model','reasoning_effort')}


def portfolio_key(context):
    # Quote/valuation refresh is not an account operation. The Account Engine
    # still checks the current quote and exposure policy when a plan executes.
    keys=('account_state_version','policy_version','binding_version','new_risk_paused','status','account_id','account_type','account_generation','cash','policy',
          'position_quantity','average_cost','available_quantity','t1_locked_quantity',
          'ownership','recent_account_actions','recent_actions','reconciliation_status',
          'new_positions_today','new_exposure_today','ai_execution_paused','ai_execution_mode')
    value={k:context.get(k) for k in keys if k in context}
    value['position']={k:v for k,v in (context.get('position') or {}).items()
        if k in ('symbol','qty','available_qty','locked_qty','avg_cost','ownership')}
    return value


def time_metadata(body,observations,events,stamp):
    day=body['session_date']
    def full(value):
        return instant(value,day).isoformat() if value else None
    def fact_time(row):
        return full(row.get('market_observed_at') or row.get('timestamp') or row.get('requested_time') or row.get('last_observation_time'))
    market_times=[fact_time(r) for r in observations+events if fact_time(r)]
    fields=[]
    for row in body['context_evidence']['observations']:
        fields.append({'source_format':row.get('source_format'),'record_id':row.get('record_id'),
            'as_of':fact_time(row),'field_times':row.get('field_times',{}),'quality':row.get('quality'),
            'missing_reasons':row.get('missing_reasons',{})})
    return {'triggered_at':max((fact_time(r) for r in body.get('trigger_events',[]) if fact_time(r)),default=None) if body['trigger_type']=='AUTO_EVENT' else None,
        'requested_at':stamp if body['trigger_type'].startswith('MANUAL') else None,
        'input_frozen_at':stamp,'data_through_at':max(market_times,key=lambda x:instant(x)) if market_times else None,
        'incremental_window':{'start':full(body['incremental_window_start']),'end':full(body['incremental_window_end']),
            'start_exclusive':bool(body.get('previous_advisory'))},
        'context_window':{'start':full(body['context_window_start']),'end':full(body['context_window_end'])},
        'source_field_times':fields,
        'structure_through_at':next((fact_time(r) for r in reversed(observations) if r.get('source_format')=='V2A_NATIVE_EXPORT_V1'),None),
        'quote_through_at':next((fact_time(r) for r in reversed(observations) if r.get('price') is not None),None)}


def event_summary(events,day):
    times=[instant(e.get('event_time') or e.get('timestamp'),day) for e in events]
    latest=max((t for t in times if t),default=None)
    counts={}
    for event,at in zip(events,times):
        if at and latest and 0<=(latest-at).total_seconds()<=900:
            key=event.get('summary') or event.get('label') or event.get('event_type') or event.get('type')
            counts[key]=counts.get(key,0)+1
    return {'through_at':latest.isoformat() if latest else None,'window_seconds':900,'counts':counts,
        'text':'；'.join(f'近15分钟出现{n}次“{k}”类事件' for k,n in counts.items())}
