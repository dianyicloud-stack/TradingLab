"""User-facing terms shared with Live; raw contracts and Opinions stay immutable."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contracts.live.notification import WORDS

TERMS={**WORDS,'volume_context':'量能对比','target_volume':'目标成交量',
    'historical_average':'历史平均成交量','sample_count':'有效样本数','actual_samples':'有效样本数',
    'requested_samples':'请求样本数','sample_start':'样本起始日期','sample_end':'样本截止日期',
    'target_trading_days':'有效交易日数','target_start':'目标起始日期','target_end':'目标截止日期',
    'ratio':'量比','amount':'成交额','volume':'成交量','period':'周期','complete':'完整状态',
    'null':'数据未提供','DAY':'日','WEEK':'周','MONTH':'月','true':'是','false':'否',
    'SINA_DAILY_RAW':'新浪日线','SINA_DAILY':'新浪日线','SINA_CN_DAILY':'新浪日线'}
PATTERN=re.compile(r'(?<![A-Za-z0-9_])('+ '|'.join(re.escape(k) for k in sorted(TERMS,key=len,reverse=True))+r')(?![A-Za-z0-9_])')
PERIOD={'DAY':'日','WEEK':'周','MONTH':'月'}

def volume(value):
    """Normalized shares only: abs >= 10000 -> W, max 2 decimals, half up."""
    try:
        n=Decimal(str(value))
        if not n.is_finite():raise InvalidOperation
    except (InvalidOperation,ValueError,TypeError):return '数据未提供'
    large=abs(n)>=10000
    if large:n=(n/10000).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    text=format(n,'f')
    if '.' in text:text=text.rstrip('0').rstrip('.')
    return ('0' if text in ('-0','') else text)+('W' if large else '')

def chinese_prose(value,share_values=()):
    """Exact known tokens / unit expressions only; unknown technical lines are diagnostic."""
    if not isinstance(value,str) or not value:return '本轮未提供'
    lines=[]
    for line in value.splitlines():
        # Never edit arbitrary URLs, identifiers or unknown code fragments into prose.
        if re.search(r'https?://|[A-Za-z]+_[A-Za-z_]+',PATTERN.sub('',line)):
            lines.append('本段含未识别的技术表达，请展开诊断原文核对。');continue
        text=re.sub(r'成交额\s*amount(?![A-Za-z0-9_])','成交额',line)
        text=re.sub(r'(?<![A-Za-z0-9_])amount\s*[:=]\s*null(?![A-Za-z0-9_])','成交额数据未提供',text)
        text=re.sub(r'(?<![A-Za-z0-9_])ratio\s*[:=]\s*(-?\d+(?:\.\d+)?)(?![\d.])',r'量比\1倍',text)
        text=PATTERN.sub(lambda m:TERMS[m[0]],text)
        text=re.sub(r'(?<![A-Za-z0-9_])(?:sh|sz|bj)(\d{6})(?!\d)',r'\1',text)
        # A visible 股 suffix proves this is a share count, not a price or amount.
        text=re.sub(r'(?<![A-Za-z0-9.])(-?\d[\d,]*(?:\.\d+)?)\s*(亿|万)?股',
            lambda m:volume(Decimal(m[1].replace(',',''))*({'亿':100000000,'万':10000}.get(m[2],1)))+'股',text)
        def known_shares(m):
            n=Decimal(m[2].replace(',',''))
            # Mean alone is ambiguous; convert only when it matches owned volume evidence.
            if ('平均' in m[1] or '均值' in m[1]) and not any(abs(n-Decimal(str(v)))<=Decimal('.5') for v in share_values if v is not None):return m[0]
            return m[1]+volume(n)
        text=re.sub(r'((?:成交量|目标[日周月]?量能|历史平均成交量|历史平均|样本均值)\s*(?:恢复至|达到|为|是|[:：=])?\s*约?\s*)(-?\d[\d,]*(?:\.\d+)?)(?![\d.W万亿股%元倍手])',known_shares,text)
        if any(w not in ('W','AI','VWAP','Alpha','OHLC') for w in re.findall(r'[A-Za-z]+',text)):
            text='本段含未识别的技术表达，请展开诊断原文核对。'
        lines.append(text)
    return '\n'.join(lines)

def volume_summary(v):
    return (f"{PERIOD.get(v.get('period'),'未知')}量能对比：目标成交量{volume(v.get('target_volume'))}股；"
        f"历史平均成交量{volume(v.get('historical_average'))}股；"
        +(f"量比{v['ratio']:.2f}倍；" if v.get('ratio') is not None else '量比不可计算；')
        +f"有效样本{v.get('actual_samples',0)}/{v.get('requested_samples',0)}；"
        +f"样本范围{v.get('sample_start') or '未提供'}至{v.get('sample_end') or '未提供'}；"
        +f"目标周期{'完整' if v.get('complete') else '未完成，按相同有效交易日进度比较'}，{v.get('target_trading_days',0)}个有效交易日。")

def history_display(job):
    opinion=job.get('opinion') or {};frozen=job.get('input') or {}
    volumes=frozen.get('volume_context') or {};share_values=(volumes.get('target_volume'),volumes.get('historical_average'))
    return {'analysis':{k:chinese_prose(v,share_values) for k,v in opinion.get('analysis',{}).items()},
            'volume_summary':volume_summary(frozen['volume_context']) if frozen.get('volume_context') else ''}

TERMS.update({"medium":"中","xhigh":"更高","PROVIDER_REFUSAL":"服务商拒绝回答","OUTPUT_TRUNCATED":"输出达到上限，结果不完整"})
