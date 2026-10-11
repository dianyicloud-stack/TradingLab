"""Cutoff first, deterministic aggregation and matched trading-day volume windows."""
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import calendar,math
from contracts.history.bars import HistoryError,request
from shared.serialization import digest

TZ=ZoneInfo('Asia/Shanghai')
def bounds(day,period):
    d=date.fromisoformat(day)
    if period=='DAY':return day,day
    if period=='WEEK':start=d-timedelta(days=d.weekday());end=start+timedelta(days=6)
    else:start=d.replace(day=1);end=d.replace(day=calendar.monthrange(d.year,d.month)[1])
    return start.isoformat(),end.isoformat()

def normalize(raw,end,now,source):
    """Never interpret fetch time as historical availability; unadjusted EOD facts only."""
    result={};issues=[]
    for row in raw:
        if not isinstance(row,dict):issues.append('INVALID_ROW');continue
        day=str(row.get('day',''))[:10]
        try:date.fromisoformat(day)
        except ValueError:issues.append('INVALID_DATE');continue
        if day>end:continue
        close_time=datetime.fromisoformat(day+'T15:00:00').replace(tzinfo=TZ)
        complete=close_time<=now
        try:
            v={k:float(row[k]) for k in ('open','high','low','close','volume')}
            if not all(math.isfinite(x) for x in v.values()) or min(v[k] for k in ('open','high','low','close'))<=0 or v['volume']<0:raise ValueError()
            if v['high']<max(v['open'],v['close'],v['low']) or v['low']>min(v['open'],v['close']):raise ValueError()
        except (KeyError,TypeError,ValueError):issues.append('INVALID_BAR:'+day);continue
        bar={'date':day,**v,'amount':None,'complete':complete,'source':source,'available_at':day+'T15:00:00+08:00' if complete else None,
             'volume_unit':'SHARE','amount_unit':'CNY','raw':dict(row),'missing':['amount']+(['NO_TRADES'] if not v['volume'] else [])}
        if day in result and result[day]!=bar:raise HistoryError('CONFLICTING_DAILY_BAR','相同日期出现不同日线，已停止分析。')
        result[day]=bar
    return sorted(result.values(),key=lambda r:r['date']),sorted(set(issues))

def aggregate(daily,period,end,market_days,is_open):
    groups=defaultdict(list)
    for b in daily:
        if b['date']>end:raise HistoryError('HISTORY_FUTURE_DATA','历史窗口包含未来日期。')
        groups[bounds(b['date'],period)[0]].append(b)
    result=[];known=set(market_days)
    for start,rows in sorted(groups.items()):
        _,finish=bounds(rows[-1]['date'],period)
        expected=sorted(d for d in known if start<=d<=min(finish,end))
        dates={r['date'] for r in rows};missing=sorted(set(expected)-dates)
        # A prior period is closed using only market dates already <= cutoff.
        closed=period=='DAY' or finish<=end or any(finish<d<=end for d in known)
        calendar_known=True
        if not closed:
            try:
                d=date.fromisoformat(end)+timedelta(days=1);remaining=[]
                while d.isoformat()<=finish:
                    if is_open(d.isoformat()):remaining.append(d.isoformat())
                    d+=timedelta(days=1)
                closed=not remaining
            except ValueError:calendar_known=False
        left_proven=bool(known) and min(known)<=start or period=='DAY'
        # Calendar can prove a Monday/first-of-month closure at coverage start.
        if not left_proven:
            try:
                d=date.fromisoformat(start);missing_head=False
                while d.isoformat()<rows[0]['date']:
                    missing_head=missing_head or is_open(d.isoformat());d+=timedelta(days=1)
                left_proven=not missing_head
            except ValueError:pass
        members=[{k:r[k] for k in ('date','volume','complete')} for r in rows]
        volume=sum(r['volume'] for r in rows)
        amounts=[r['amount'] for r in rows if r['amount'] is not None]
        result.append({'date':rows[-1]['date'],'period_start':start,'period_end':finish,'open':rows[0]['open'],
            'high':max(r['high'] for r in rows),'low':min(r['low'] for r in rows),'close':rows[-1]['close'],
            'volume':volume,'amount':sum(amounts) if amounts else None,'amount_complete':len(amounts)==len(rows),
            'complete':bool(closed and all(r['complete'] for r in rows) and not missing and left_proven),
            'source':rows[0]['source'],'constituent_count':len(rows),'members':members,
            'calendar_known':calendar_known,'left_boundary_proven':left_proven,
            'missing_dates':missing,'missing':['amount'] if not amounts else [],
            'valid_volume':not missing and left_proven and all(r['complete'] and r['volume']>0 for r in rows),
            'available_at':rows[-1]['available_at'],'raw':rows[0]['raw'] if period=='DAY' else None})
    return result

def volume_context(groups,samples,period):
    if not groups:return {'status':'NO_DATA','period':period,'actual_samples':0,'requested_samples':samples,'ratio':None}
    target=groups[-1];progress=len(target['members']);comparisons=[]
    for g in groups[:-1]:
        if not g['valid_volume'] or not g['complete']:continue
        if target['complete']:selected=g['members']
        else:
            if len(g['members'])<progress:continue
            selected=g['members'][:progress]
        comparisons.append({'start':selected[0]['date'],'end':selected[-1]['date'],'volume':sum(r['volume'] for r in selected),'trading_days':len(selected)})
    comparisons=comparisons[-samples:];avg=sum(r['volume'] for r in comparisons)/len(comparisons) if comparisons else None
    valid=target['valid_volume']
    return {'period':period,'target_start':target['period_start'],'target_end':target['date'],'target_trading_days':progress,
        'complete':target['complete'],'comparison_basis':'FULL_PERIOD' if target['complete'] else 'MATCHED_TRADING_DAY_PROGRESS',
        'target_volume':target['volume'],'historical_average':avg,'ratio':target['volume']/avg if valid and avg else None,
        'requested_samples':samples,'actual_samples':len(comparisons),'samples':comparisons,
        'sample_start':comparisons[0]['start'] if comparisons else None,'sample_end':comparisons[-1]['end'] if comparisons else None,
        'status':'TARGET_INCOMPLETE_EVIDENCE' if not valid else 'OK' if len(comparisons)==samples else 'INSUFFICIENT_SAMPLES'}

class BarsEngine:
    def __init__(self,cache,adapter,calendar,clock=None):
        self.cache,self.adapter,self.calendar=cache,adapter,calendar
        self.clock=clock or (lambda:datetime.now(TZ))
    def read(self,value):
        q=request(value);now=self.clock();end=q['end_date']
        if end>now.astimezone(TZ).date().isoformat():raise HistoryError('FUTURE_DATE','截止日期不能晚于今天。')
        buffer=2 if q['period']==q['volume_period']=='DAY' else 35
        needed=max(q['limit']*{'DAY':1,'WEEK':5,'MONTH':23}[q['period']],(q['samples']+2)*{'DAY':1,'WEEK':5,'MONTH':23}[q['volume_period']])+buffer
        lag=max(0,(now.date()-date.fromisoformat(end)).days*5//7)
        count=next((n for n in (64,256,768,1970) if n>=needed+lag),1970)
        raw=self.cache.daily(q['symbol'],count,self.adapter,now)
        benchmark=self.cache.daily('sh000001',count,self.adapter,now)
        days=[str(r.get('day',''))[:10] for r in benchmark if str(r.get('day',''))[:10]<=end]
        daily,issues=normalize(raw,end,now,self.adapter.source)
        if not daily:raise HistoryError('OUTSIDE_COVERAGE','截止日无可用日线；可能超出来源范围或该股尚未上市。')
        chart=aggregate(daily,q['period'],end,days,self.calendar.is_open)[-q['limit']:]
        volumes=volume_context(aggregate(daily,q['volume_period'],end,days,self.calendar.is_open),q['samples'],q['volume_period'])
        out={**q,'schema_version':'1.0','exchange':q['symbol'][:2].upper(),'timezone':'Asia/Shanghai','source':self.adapter.source,
            'requested_end_date':end,'actual_end_date':daily[-1]['date'],'coverage_start':daily[0]['date'],'coverage_end':daily[-1]['date'],
            'bars':chart,'volume_context':volumes,'quality':{'issues':issues,'missing_amount':True,'unadjusted':True,
            'source_maximum':1970,'requested_bars':q['limit'],'actual_bars':len(chart),'scope':'RECONSTRUCTED_EOD_NOT_ORIGINAL_VINTAGE',
            'gaps_or_suspensions':sorted(set(d for b in chart for d in b['missing_dates'])|
                {d for d in days if chart[0]['period_start']<=d<=daily[-1]['date'] and d not in {r['date'] for r in daily}}),'future_rows_excluded':True}}
        out['data_version']=digest(out);out['fingerprint']=out['data_version']
        return out
