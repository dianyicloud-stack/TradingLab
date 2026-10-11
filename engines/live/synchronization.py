"""Compare owner/applied fact watermarks, not AI or browser refresh times."""
from engines.live.native_health import instant
from datetime import datetime
GRACE_SECONDS=15  # three 5-second listener cycles; not a market freshness limit

def status(session,applied,now):
    source=session.get('source_watermark');read=applied.get('source_watermark')
    result={'status':'UNKNOWN','source_watermark':source,'applied_watermark':read,'grace_seconds':GRACE_SECONDS,
            'lag_seconds':None,'source_data_time':session.get('last_observation_time'),
            'listener_data_time':applied.get('listener_observation_cursor'),'read_at':applied.get('read_at')}
    if session.get('source_errors') or applied.get('errors'):
        result.update(status='SOURCE_ERROR',reason='SOURCE_OR_INGESTION_ERROR');return result
    if not source:return result
    if not read:result.update(status='NOT_SYNCED',reason='NO_APPLIED_WATERMARK');return result
    if source['identity']!=read['identity']:result.update(status='SOURCE_IDENTITY_MISMATCH');return result
    if source['version']==read['version']:result.update(status='SYNCED',lag_seconds=0);return result
    if source['version']<read['version']:result.update(status='SOURCE_VERSION_REGRESSED');return result
    # The owner supplies the first not-yet-applied commit, from this same snapshot.
    commits=session.get('source_commits',[])
    first=next((r['at'] for r in commits if r['version']>read['version']),None)
    if not first:result.update(status='PENDING',reason='COMMIT_TIME_UNKNOWN');return result
    try:
        stamp=datetime.fromisoformat(first.replace('Z','+00:00'))
        if stamp.tzinfo is None or now.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    except (ValueError,TypeError,AttributeError):
        result.update(status='PENDING',reason='COMMIT_TIME_UNKNOWN');return result
    age=(now-stamp).total_seconds()
    if age<0:result.update(status='CLOCK_SKEW',reason='FUTURE_SOURCE_COMMIT');return result
    result.update(status='LAGGING' if age>GRACE_SECONDS else 'PENDING',lag_seconds=round(age,1),
                  pending_since=first,reason='OWNER_COMMIT_NOT_APPLIED')
    return result
