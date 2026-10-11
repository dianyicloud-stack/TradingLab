"""Same Sina daily endpoint as the native Agent; isolated read-only HTTP."""
from urllib.request import Request,urlopen
from urllib.parse import urlencode
import json
from contracts.history.bars import HistoryError

class SinaDailyBars:
    source='SINA_DAILY_RAW'
    maximum=1970
    def fetch(self,symbol,count):
        url='https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?'+urlencode(dict(symbol=symbol,scale=240,ma='no',datalen=min(count,self.maximum)))
        try:
            with urlopen(Request(url,headers={'Referer':'https://finance.sina.com.cn/','User-Agent':'TradingLab-History/1.0'}),timeout=12) as response:
                value=json.loads(response.read(2*1024*1024))
        except (OSError,ValueError):raise HistoryError('HISTORY_SOURCE_UNAVAILABLE','日线来源暂不可用，请稍后重试。',503) from None
        if not isinstance(value,list):raise HistoryError('HISTORY_NO_DATA','来源没有返回该股票日线。')
        return value
