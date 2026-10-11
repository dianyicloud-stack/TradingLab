"""Opt-in deterministic Live changes, separate from the native event sequence."""
from engines.live.native_health import instant
from engines.live.reading import fingerprint

RULE='LIVE_PRICE_MOVE_60S'
RULES={RULE:'即时价格变化（默认关闭）'}
DEFAULT={'version':'1','window_seconds':60,'threshold_percent':1.0,'cooldown_seconds':60,'max_sample_gap_seconds':20}


def detect(runtime,facts,settings,now):
    identity=facts['session']['tracking_session_id']
    samples=[r for r in facts['observations'] if r.get('source_format')=='V2A_RUNTIME_SNAPSHOT_V1']
    selected=RULE in (settings.get('auto_event_types') or [])
    config={**DEFAULT,**settings.get('live_trigger_config',{})}
    state=runtime.native_control(identity,'TRIGGER_BASELINE')
    if not samples:return
    newest=samples[-1];signature=fingerprint({'selected':selected,'config':config})
    previous_read=instant(state.get('read_at')) if state else None
    last_market=instant(state['samples'][-1]['market_observed_at']) if state and state.get('samples') else None
    unseen=[r for r in samples if not last_market or instant(r['market_observed_at'])>last_market]
    recovery=bool(state and (previous_read and (now-previous_read).total_seconds()>config['max_sample_gap_seconds'] or
        any(r.get('delivery')!='LIVE' or r.get('publisher_id')!=state.get('publisher') for r in unseen)))
    if not state or state.get('configuration')!=signature or recovery:
        runtime.save_native_control(identity,'TRIGGER_BASELINE',{'configuration':signature,'last_id':newest['record_id'],
            'publisher':newest['publisher_id'],'samples':[newest],'last_triggered_at':None,'read_at':now.isoformat()});return
    rows=state.get('samples',[]);last_time=instant(rows[-1]['market_observed_at']) if rows else None
    triggers=runtime.native_control(identity,'LIVE_TRIGGERS') or []
    for row in samples:
        at=instant(row['market_observed_at'])
        if row['record_id']==state['last_id'] or last_time and at<=last_time:continue
        gap=(at-last_time).total_seconds() if last_time else None
        reset=row.get('delivery')!='LIVE' or row.get('publisher_id')!=state.get('publisher') or gap is None or gap>config['max_sample_gap_seconds'] or (now-at).total_seconds()>30
        state.update(last_id=row['record_id'],publisher=row.get('publisher_id'))
        if reset:rows=[row];last_time=at;continue
        rows=[r for r in rows if 0<(at-instant(r['market_observed_at'])).total_seconds()<=config['window_seconds']]
        baseline=rows[0] if rows else None
        cooled=not state.get('last_triggered_at') or (at-instant(state['last_triggered_at'])).total_seconds()>=config['cooldown_seconds']
        if selected and baseline and baseline.get('price',0)>0 and cooled:
            change=(row['price']/baseline['price']-1)*100
            if abs(change)>=config['threshold_percent']:
                evidence={'before_id':baseline['record_id'],'after_id':row['record_id'],'before_price':baseline['price'],
                    'after_price':row['price'],'window_start':baseline['market_observed_at'],'window_end':row['market_observed_at']}
                trigger={'trigger_id':'LTR-'+fingerprint({'rule':config,'evidence':evidence})[:32],
                    'source':'LIVE_TRIGGER','type':RULE,'severity':'IMPORTANT','timestamp':row['market_observed_at'],
                    'symbol':row['symbol'],'tracking_session_id':identity,'rule':config,'evidence':evidence,
                    'change_percent':round(change,6),'summary':'短窗口价格变化','price':row['price']}
                if not any(t['trigger_id']==trigger['trigger_id'] for t in triggers):triggers.append(trigger)
                state['last_triggered_at']=row['market_observed_at']
        rows.append(row);last_time=at
    state['samples']=rows
    state['read_at']=now.isoformat()
    runtime.save_native_control(identity,'TRIGGER_BASELINE',state)
    runtime.save_native_control(identity,'LIVE_TRIGGERS',triggers)
