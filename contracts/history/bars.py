"""Portable daily/weekly/monthly observation requests; no intraday history."""
from datetime import date
import re

PERIODS=('DAY','WEEK','MONTH')
class HistoryError(ValueError):
    def __init__(self,code,message,status=422):
        super().__init__(message);self.code,self.http_status=code,status

def request(value):
    if set(value)-{'symbol','period','end_date','limit','adjustment','volume_period','samples'}:
        raise HistoryError('INVALID_FIELDS','历史请求含不支持的字段。',400)
    symbol=value.get('symbol','')
    if not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):raise HistoryError('INVALID_SYMBOL','请输入带市场前缀的六位股票代码。',400)
    try:
        day=date.fromisoformat(value['end_date']).isoformat()
        limit=int(value.get('limit',31));samples=int(value.get('samples',20))
    except (KeyError,TypeError,ValueError):raise HistoryError('INVALID_REQUEST','请指定有效截止日期和样本数。',400) from None
    period=value.get('period','DAY');volume=value.get('volume_period','DAY')
    if period not in PERIODS or volume not in PERIODS:raise HistoryError('UNSUPPORTED_PERIOD','历史仅支持日、周、月。',400)
    if not 1<=limit<=500 or samples not in (10,20,30,60):raise HistoryError('INVALID_RANGE','图表最多500根，量能样本为10/20/30/60。',400)
    if value.get('adjustment','NONE')!='NONE':raise HistoryError('UNSUPPORTED_ADJUSTMENT','当前仅支持不复权，避免未来复权因素进入历史分析。',400)
    return dict(symbol=symbol,end_date=day,period=period,volume_period=volume,limit=limit,samples=samples,adjustment='NONE')
