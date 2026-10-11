"""Bounded 0/30/60 minute browser metrics from the running soak's samples."""
from pathlib import Path
import json,math,sys,time
root=Path(sys.argv[1]);captured={};last_raw=None
def percentile(values,p):return sorted(values)[max(0,math.ceil(len(values)*p)-1)] if values else None
while True:
    try:value=json.loads((root/'browser.json').read_text())
    except (OSError,ValueError):time.sleep(3);continue
    elapsed=value.get('elapsedSeconds',0)
    if any('times' in r for r in value.get('routes',{}).values()):last_raw=value
    for label,at in [('start',0),('30m',1800),('60m',3600)]:
        if label in captured or elapsed<at:continue
        rows={}
        sample_value=last_raw or value
        for key,row in sample_value.get('routes',{}).items():
            if not key.startswith(('normal ','direct-normal ')):continue
            series=row.get('times',[])
            sample=series[:10] if label=='start' else series[-10:]
            rows[key]={'sample_policy':'first 10 normal reads' if label=='start' else 'latest 10 normal reads',
                       'samples':len(sample),'p50_ms':percentile(sample,.5),'p95_ms':percentile(sample,.95),
                       'cumulative_count':row['count'],'cumulative_failures':row['failures']}
        captured[label]={'observed_elapsed_seconds':elapsed,'sample_cutoff_seconds':sample_value.get('elapsedSeconds'), 'routes':rows,'resource_checkpoint':value.get('checkpoints',[])[-1:],
                         'warning':'start metrics reconstructed from retained first samples; resource startup is in browser.json checkpoints[start]' if label=='start' else None}
        (root/'phase-metrics.json').write_text(json.dumps(captured,ensure_ascii=False,indent=2),encoding='utf-8')
    if '60m' in captured or value.get('status')!='RUNNING':break
    time.sleep(3)
