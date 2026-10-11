"""Central cash-equity simulation rules; only ordinary SH/SZ/BJ A-shares.

Exchange sources and covered calendar years are documented in M2_2_3.
Unknown calendars/instruments fail closed rather than guessing holiday sessions.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math
import re
from contracts.account.portfolio import AccountError

TZ = timezone(timedelta(hours=8))


def amount(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def number(value, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise AccountError('INVALID_NUMBER', status=400)
    return value


def instant(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise AccountError('INVALID_MARKET_TIME', status=400) from None


class TradingCalendar:
    def __init__(self, holidays=None, years=(2025, 2026)):
        self.years = set(years)
        spans = [('2025-01-01','2025-01-01'),('2025-01-28','2025-02-04'),('2025-04-04','2025-04-06'),
                 ('2025-05-01','2025-05-05'),('2025-05-31','2025-06-02'),('2025-10-01','2025-10-08'),
                 ('2026-01-01','2026-01-03'),('2026-02-15','2026-02-23'),('2026-04-04','2026-04-06'),
                 ('2026-05-01','2026-05-05'),('2026-06-19','2026-06-21'),('2026-09-25','2026-09-27'),('2026-10-01','2026-10-07')]
        self.holidays = set(holidays or [])
        if holidays is None:
            for start, end in spans:
                day, last = date.fromisoformat(start), date.fromisoformat(end)
                while day <= last:
                    self.holidays.add(day.isoformat()); day += timedelta(days=1)

    def is_open(self, day):
        value = date.fromisoformat(day)
        if value.year not in self.years: raise AccountError('CALENDAR_UNAVAILABLE')
        return value.weekday() < 5 and day not in self.holidays

    def next_day(self, day):
        value = date.fromisoformat(day) + timedelta(days=1)
        while not self.is_open(value.isoformat()): value += timedelta(days=1)
        return value.isoformat()


class MarketRuleService:
    def __init__(self, calendar=None): self.calendar = calendar or TradingCalendar()

    def rule(self, symbol):
        if not isinstance(symbol,str) or not re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})',symbol):
            raise AccountError('UNSUPPORTED_INSTRUMENT')
        star, bj, growth = symbol.startswith('sh688'), symbol.startswith('bj'), symbol.startswith('sz30')
        return {'market':symbol[:2].upper(), 'minimum':200 if star else 100,
                'increment':1 if star or bj else 100, 'price_tick':.01,
                'ordinary_price_limit':.30 if bj else .20 if star or growth else .10, 't_plus_one':True}

    def round_qty(self, symbol, qty, *, sell=False, available=0):
        rule = self.rule(symbol); qty = max(0,int(qty))
        if sell and qty >= available: return available
        return 0 if qty < rule['minimum'] else qty // rule['increment'] * rule['increment']

    def session(self, timestamp):
        value = instant(timestamp).astimezone(TZ)
        hhmm = value.strftime('%H:%M:%S')
        return self.calendar.is_open(value.date().isoformat()) and ('09:30:00' <= hhmm <= '11:30:00' or '13:00:00' <= hhmm <= '15:00:00')

    def fees(self, gross, side, model):
        commission = amount(max(model['minimum_commission'],gross*model['commission_rate'])) if gross else 0
        transfer = amount(gross*model['transfer_rate'])
        stamp = amount(gross*model['sell_stamp_rate']) if side == 'SELL' else 0
        return {'commission':commission,'transfer_fee':transfer,'stamp_duty':stamp,'total':amount(commission+transfer+stamp)}


def validate_policy(payload):
    names = ('max_open_positions','max_new_positions_per_day','max_position_weight_per_symbol','max_total_exposure_pct',
             'max_new_exposure_per_day_pct','minimum_cash_reserve_pct','fee_model','slippage_model','ai_execution_mode')
    if set(payload) != set(names): raise AccountError('POLICY_FIELDS_REQUIRED', status=400)
    p = dict(payload)
    for key in names[:2]:
        if type(p[key]) is not int or not 1 <= p[key] <= 10000: raise AccountError('INVALID_POLICY',status=400)
    for key in names[2:6]: number(p[key],0,1)
    if p['ai_execution_mode'] not in ('OFF','ADVISORY_ONLY','AUTO_SHADOW_EXECUTION'): raise AccountError('INVALID_AI_EXECUTION_MODE')
    fee=p['fee_model']; slip=p['slippage_model']
    if not isinstance(fee,dict) or set(fee)!= {'commission_rate','minimum_commission','transfer_rate','sell_stamp_rate'}: raise AccountError('INVALID_FEE_MODEL')
    for key,value in fee.items(): number(value,0,100 if key=='minimum_commission' else .1)
    if not isinstance(slip,dict) or set(slip)!= {'kind','bps'} or slip['kind']!='FIXED_BPS': raise AccountError('INVALID_SLIPPAGE_MODEL')
    number(slip['bps'],0,1000)
    return p


# Existing product defaults, centrally exposed for explicit user creation.
DEFAULT_POLICY={'max_open_positions':5,'max_new_positions_per_day':2,'max_position_weight_per_symbol':.3,
    'max_total_exposure_pct':.8,'max_new_exposure_per_day_pct':.4,'minimum_cash_reserve_pct':.1,
    'fee_model':{'commission_rate':.0003,'minimum_commission':5,'transfer_rate':.00001,'sell_stamp_rate':.0005},
    'slippage_model':{'kind':'FIXED_BPS','bps':5},'ai_execution_mode':'ADVISORY_ONLY'}
