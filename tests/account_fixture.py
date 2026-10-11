from copy import deepcopy

POLICY={'max_open_positions':5,'max_new_positions_per_day':2,'max_position_weight_per_symbol':.3,
        'max_total_exposure_pct':.8,'max_new_exposure_per_day_pct':.4,'minimum_cash_reserve_pct':.1,
        'fee_model':{'commission_rate':.0003,'minimum_commission':5,'transfer_rate':.00001,'sell_stamp_rate':.0005},
        'slippage_model':{'kind':'FIXED_BPS','bps':5},'ai_execution_mode':'ADVISORY_ONLY'}


def policy(**overrides):return {**deepcopy(POLICY),**overrides}


def quote(symbol='bj920161',price=10,time='2026-09-10T10:00:00+08:00'):
    return {'symbol':symbol,'price':price,'quote_time':time,'available_at':time,'quote_source':'TEST_FIXTURE','freshness':'FRESH'}

