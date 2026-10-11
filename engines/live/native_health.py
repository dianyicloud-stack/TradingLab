"""Market age, exporter state and ingestion delay are independent evidence."""
from datetime import datetime, timezone, timedelta
TZ=timezone(timedelta(hours=8))

def instant(value,day=None):
    if not value:return None
    text=str(value)
    if 'T' not in text and ' ' in text:text=text.replace(' ','T',1)
    if 'T' not in text and day:text=f'{day}T{text}'
    result=datetime.fromisoformat(text.replace('Z','+00:00'))
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result

def health(session,now,is_open):
    now=now.astimezone(TZ);day=session.get('session_date') or session.get('market_date')
    export=session.get('export_status') or {}
    try: open_day=is_open(now.date().isoformat())
    except Exception:open_day=None
    hhmm=now.strftime('%H:%M')
    phase='CALENDAR_UNKNOWN' if open_day is None else 'NON_TRADING_DAY' if not open_day else (
        'BEFORE_OPEN' if hhmm<'09:30' else 'LUNCH_BREAK' if '11:30'<hhmm<'13:00' else 'CLOSED' if hhmm>'15:00' else 'TRADING')
    latest=session.get('market_observed_at') or session.get('latest_complete_observation_time') or session.get('last_observation_time')
    observed=instant(latest,day);event=instant(session.get('last_event_time'),day)
    age=max(0,int((now-observed).total_seconds())) if observed else None
    state='UNKNOWN' if not observed else 'FRESH'
    if not observed: state='OBSERVATION_MISSING' if event else 'WAITING_FIRST_DATA'
    elif phase=='NON_TRADING_DAY':state='NON_TRADING_DAY'
    elif phase=='BEFORE_OPEN':state='WAITING_FIRST_DATA'
    elif observed.date()!=now.date():state='STALE'
    elif phase=='CLOSED':state='CLOSE_COMPLETE' if observed.strftime('%H:%M')>='15:00' else 'CLOSE_TAIL_MISSING'
    elif phase=='LUNCH_BREAK':state='LUNCH_BREAK' if observed.strftime('%H:%M')>='11:30' else 'STALE'
    else:
        interval=5 if session.get('latest_snapshot_time') else export.get('expected_observation_interval_seconds',300 if session.get('native_export') else 30)
        grace=export.get('observation_grace_seconds',90)
        if age>interval+grace:state='STALE'
    heartbeat=instant(export.get('heartbeat_at'))
    exporter_state=export.get('state','UNKNOWN')
    if heartbeat and (now-heartbeat).total_seconds()>30:exporter_state='UNKNOWN'
    if session.get('source_errors'):state='SOURCE_ERROR'
    return {'status':state,'market_phase':phase,'market_data_time':latest,'market_age_seconds':age,
      'structure_time':session.get('latest_structure_time'),
      'evidence_status':'SNAPSHOT_WITHOUT_STRUCTURE' if session.get('latest_snapshot_time') and not session.get('latest_structure_time') else None,
      'event_age_seconds':max(0,int((now-event).total_seconds())) if event else None,
      'exporter_state':exporter_state,'observation_task':export.get('observation_task','UNKNOWN') if exporter_state!='UNKNOWN' else 'UNKNOWN',
      'quick_sample_task':export.get('quick_sample_task','UNKNOWN') if exporter_state!='UNKNOWN' else 'UNKNOWN',
      'expected_interval_seconds':export.get('expected_observation_interval_seconds'),
      'sync_latency_seconds':None, 'errors':session.get('source_errors',[])}
