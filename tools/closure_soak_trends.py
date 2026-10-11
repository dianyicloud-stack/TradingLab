"""Read-only sidecar of isolated soak artifacts; retain ordered latency trends."""
from pathlib import Path
import json,time,sys
base=Path(sys.argv[1]);rows=[];previous={}
def quantile(values,q):
    values=sorted(values)
    return values[min(len(values)-1,int(len(values)*q))] if values else None
while True:
    try:
        browser=json.loads((base/'browser.json').read_text(encoding='utf-8'))
        samples=json.loads((base/'samples.json').read_text(encoding='utf-8'))
        routes={}
        for name,value in browser['routes'].items():
            times=value.get('times',[]);start=previous.get(name,0);recent=times[start:]
            routes[name]={'count':value['count'],'errors':value['errors'],'interval_samples':len(recent),'p50_ms':quantile(recent,.5),'p95_ms':quantile(recent,.95)}
            previous[name]=len(times)
        rows.append({'seconds':browser.get('elapsed_seconds',0),'routes':routes,'peak_inflight':browser['peak_inflight'],
            'pageerror':len(browser['pageerror']),'console_error':len(browser['console_error']),
            'latest_runtime':{k:samples[-1][k] for k in ('elapsed_seconds','memory','fact_count','event_count','fake_calls','opinion_count','listener_error')}})
        (base/'performance-trends.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        if browser['status']!='RUNNING':break
    except (OSError,ValueError,KeyError):pass
    time.sleep(30)
print(json.dumps({'trend_checkpoints':len(rows),'seconds':rows[-1]['seconds'] if rows else 0}))
