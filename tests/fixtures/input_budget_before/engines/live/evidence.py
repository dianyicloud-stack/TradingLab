"""Versioned AI evidence projection. Raw facts and frozen cursors remain unchanged."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from contracts.live.bridge import BridgeError

VERSION = 'live-evidence-2.0'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def estimate(text):
    # Engineering estimate; NOT an exact tokenizer or an upper bound. The
    # transport also checks a separate UTF-8 byte bound against model context.
    return math.ceil(sum(1/3 if ord(c) < 128 else 1.5 for c in text))


def at(row):
    return row.get('timestamp') or row.get('market_observed_at') or row.get('sampled_at')


def tabulate(rows):
    """Lossless common-value/column encoding; missing differs from explicit null."""
    if not rows:return {'columns': [], 'rows': []}
    def flatten(row,prefix=''):
        out={}
        for key,value in row.items():
            path=prefix+'/'+key.replace('~','~0').replace('/','~1')
            if isinstance(value,dict) and value:out.update(flatten(value,path))
            else:out[path]=value
        return out
    rows=[flatten(r) for r in rows]
    keys=sorted(set().union(*(r.keys() for r in rows)))
    common={k:rows[0][k] for k in keys if k in rows[0] and all(k in r and r[k]==rows[0][k] for r in rows)}
    columns=[k for k in keys if k not in common]
    return {'encoding':'json-pointer-columns-v1','common':common,'columns':columns,
            'rows':[[r.get(k) for k in columns] for r in rows],
            'missing':[[i for i,k in enumerate(columns) if k not in r] for r in rows]}


def unique(rows):
    seen=set();result=[]
    for r in rows:
        key=digest(r)
        if key not in seen:result.append(r);seen.add(key)
    return result


def summarize(rows, events, minutes):
    """Every numeric series: interval ends/extrema; every VWAP/level crossing.

    All nonnumeric quality/provenance changes are retained as runs. This is an
    explicitly derived summary, never a fabricated native Observation/Event.
    """
    groups={};crossings=[];event_points=set()
    levels={'vwap':None}
    for event in events:
        for key,value in event.get('evidence',{}).items():
            if any(word in key.lower() for word in ('support','resistance','threshold')) and type(value) in (int,float):
                levels[key+':'+str(value)]=value
    previous={}
    for i,r in enumerate(rows):
        t=datetime.fromisoformat(at(r).replace('Z','+00:00'))
        groups.setdefault(t.isoformat()[:11]+str((t.hour*60+t.minute)//minutes),[]).append((i,r))
        values={**r.get('fields',{}),**{k:v for k,v in r.items() if type(v) in (float,int)}}
        price=values.get('price')
        for key,threshold in levels.items():
            threshold=values.get('vwap') if key=='vwap' else threshold
            if type(price) in (float,int) and type(threshold) in (float,int):
                side=(price>threshold)-(price<threshold)
                if key in previous and previous[key]!=side:crossings.append([i,key,previous[key],side,price,threshold])
                previous[key]=side
    times=[at(r) for r in rows]
    for e in events:
        t=at(e)
        if not t or not rows:continue
        moment=datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
        j=min(range(len(rows)),key=lambda i:abs(datetime.fromisoformat(times[i].replace('Z','+00:00')).timestamp()-moment))
        event_points.update(i for i in (j-1,j,j+1) if 0<=i<len(rows))
    intervals=[]
    for group in groups.values():
        series={}
        for i,r in group:
            values={**r.get('fields',{}),**{k:v for k,v in r.items() if type(v) in (float,int)}}
            for key,value in values.items():
                if type(value) in (int,float):series.setdefault(key,[]).append([i,value])
        intervals.append({'range':[group[0][0],group[-1][0]],'metrics':{
            k:[v[0],v[-1],min(v,key=lambda p:p[1]),max(v,key=lambda p:p[1])] for k,v in series.items()}})
    # Retain missing, quality and field-clock anomalies, including their order.
    runs=[];last=None
    for i,r in enumerate(rows):
        flags={k:v for k,v in r.items() if any(s in k.lower() for s in ('quality','missing','trusted','error','gap','complete'))}
        flags['missing_fields']=[k for k,v in r.get('fields',{}).items() if v is None]
        flags['field_clock_offsets']={k:v for k,v in r.get('field_times',{}).items() if v!={'as_of':at(r)}}
        if flags!=last:runs.append([i,flags]);last=flags
    points=sorted(event_points)
    origin=datetime.fromisoformat(times[0].replace('Z','+00:00')) if times else None
    return {'kind':'DETERMINISTIC_SNAPSHOT_SUMMARY','native':False,'interval_minutes':minutes,
            'count':len(rows),'source_series_sha256':digest(rows),'time_origin':times[0] if times else None,
            'time_offsets_seconds':[(lambda v:int(v) if v.is_integer() else v)((datetime.fromisoformat(t.replace('Z','+00:00'))-origin).total_seconds()) for t in times],
            'intervals':intervals,'crossings_columns':['sample_index','threshold','from','to','price','threshold_value'],
            'crossings':crossings,'quality_runs':runs,'event_nearby_indices':points,
            'event_nearby_points':tabulate([{k:v for k,v in rows[i].items() if k in ('timestamp','fields','quality','missing_evidence')} for i in points])}


def build(frozen, prompt, schema, *, target=None):
    target=int(target or os.environ.get('TRADING_LAB_AI_INPUT_TOKEN_TARGET','32768'))
    if target<=0:raise BridgeError('INPUT_BUDGET','AI输入预算配置无效。',422)
    inc=frozen.get('incremental_evidence',{});ctx=frozen.get('context_evidence',{})
    rows=unique(inc.get('observations',[]));events=unique(inc.get('events',[]))
    all_rows=rows+events+ctx.get('observations',[])+ctx.get('events',[])
    try:cutoff=datetime.fromisoformat((frozen.get('input_frozen_at') or frozen.get('created_at')).replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError):raise BridgeError('ADVISORY_TIME_UNPROVEN') from None
    for row in all_rows:
        if row.get('symbol',frozen['symbol'])!=frozen['symbol'] or row.get('tracking_session_id',frozen['tracking_session_id'])!=frozen['tracking_session_id']:
            raise BridgeError('EVIDENCE_IDENTITY_MISMATCH')
        for key in ('available_at','timestamp','sampled_at','market_observed_at'):
            if row.get(key) and datetime.fromisoformat(row[key].replace('Z','+00:00'))>cutoff:raise BridgeError('ADVISORY_FUTURE_DATA')
    snapshots=[r for r in rows if r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1']
    formal=[r for r in rows if r.get('source_format')!='V2A_RUNTIME_SNAPSHOT_V1']
    previous=frozen.get('previous_advisory') or {}
    previous={k:previous[k] for k in ('advisory_id','generated_at','data_through_at','action','confidence','dominant_side','dominance_score','dominance_trend','core_conflict','scenario_tree','next_observation_focus','invalidation','key_levels','previous_hypothesis_review') if k in previous}
    # Context overlaps are referenced, not duplicated. Baseline is retained.
    context_rows=[r for r in unique(ctx.get('observations',[])) if digest(r) not in {digest(x) for x in rows}]
    context_events=[r for r in unique(ctx.get('events',[])) if digest(r) not in {digest(x) for x in events}]
    header={k:deepcopy(v) for k,v in frozen.items() if k not in (
        'incremental_evidence','context_evidence','trigger_events','previous_advisory','current_state','live_observation','all_event_sequences','source_session','source_field_times')}
    for minutes in (5,15,60,240):
        evidence={**header,'input_builder_version':VERSION,'source_frozen_input_id':frozen['input_id'],
            'source_frozen_input_hash':frozen['input_hash'],'previous_advisory':previous,
            'latest_snapshot':snapshots[-1] if snapshots else None,
            'latest_observation':({'same_as':'current_state'} if frozen.get('live_observation')==frozen.get('current_state') else frozen.get('live_observation')),
            'current_state':frozen.get('current_state'),
            'formal_observations':tabulate(formal),'events':tabulate(events),
            'comparison_baseline':tabulate(context_rows),'context_events':tabulate(context_events),
            'snapshot_path':summarize(snapshots,events,minutes),
            'encoding_note':'Column paths are JSON pointers; quality and missing flags are preserved. Sample times = time_origin + time_offsets_seconds[index]. Summary is derived, not a native event.',
            'source_counts':{'snapshots':len(snapshots),'observations':len(formal),'events':len(events),'previous_opinions':int(bool(previous))}}
        # Reserve space for transport framing and the frozen provider's fixed instructions.
        tokens=estimate(encoded(evidence)+prompt+encoded(schema))+1024
        if tokens<=target:return evidence,{'input_builder_version':VERSION,'token_count_method':'CHARACTER_ESTIMATE_NOT_DEEPSEEK_TOKENIZER',
            'estimated_input_tokens':tokens,'target_input_tokens':target,'evidence_sha256':digest(evidence),'evidence_bytes':len(encoded(evidence).encode()),
            'source_counts':evidence['source_counts'],'snapshot_interval_minutes':minutes}
    raise BridgeError('INPUT_BUDGET','关键证据无法在AI输入预算内安全容纳；未调用Provider。',422)
