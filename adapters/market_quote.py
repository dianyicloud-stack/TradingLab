"""Read-only quote-provider fallback for untracked live A-share valuation."""
from datetime import datetime,timezone
from threading import RLock
from time import monotonic
from urllib.request import Request,urlopen
import re


class SinaQuoteProvider:
    def __init__(self):self.cache={};self.lock=RLock()

    def __call__(self,symbol):
        if not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):return None
        with self.lock:
            cached=self.cache.get(symbol)
            if cached and monotonic()-cached[0]<10:return cached[1]
        try:
            request=Request('https://hq.sinajs.cn/list='+symbol,headers={'Referer':'https://finance.sina.com.cn/','User-Agent':'TradingLab/0.1'})
            with urlopen(request,timeout=4) as response:body=response.read(32768).decode('gb18030')
            match=re.fullmatch(r'\s*var hq_str_'+symbol+r'="([^"]*)";\s*',body)
            fields=match[1].split(',') if match else []
            if len(fields)<32 or float(fields[3])<=0:return None
            timestamp=fields[30]+'T'+fields[31]+'+08:00';datetime.fromisoformat(timestamp)
            value={'symbol':symbol,'price':float(fields[3]),'previous_close':float(fields[2]),'quote_time':timestamp,
                   'available_at':timestamp,'quote_source':'SINA_QUOTE_PROVIDER','freshness':'FRESH','instrument_name':fields[0]}
        except (OSError,ValueError,IndexError):value=None
        with self.lock:self.cache[symbol]=(monotonic(),value)
        return value
