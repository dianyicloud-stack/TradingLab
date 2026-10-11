"""Clock-bound quote routing. Sandbox contexts cannot reach the live fallback."""
from contracts.account.portfolio import AccountError
from engines.account.rules import instant, TZ


class QuoteService:
    def __init__(self,live_source,fallback=None):
        self.live_source,self.fallback=live_source,fallback

    def clock(self,account,live_now):
        if account['account_type']!='LIVE_SHADOW':raise AccountError('ACCOUNT_READ_ONLY')
        return live_now

    def quote(self,account,symbol,visible_through):
        if account['account_type']!='LIVE_SHADOW':raise AccountError('ACCOUNT_READ_ONLY')
        source=self.live_source
        row=next((x for x in source.sessions() if x['symbol']==symbol),None)
        observation=source.latest_observation(row['tracking_session_id']) if row and row.get('tracking_session_id') else row
        quote=None
        if observation and observation.get('price') is not None:
            time=observation.get('timestamp') or observation.get('requested_time') or observation.get('last_observation_time')
            if time and 'T' not in time:time=(row.get('market_date') or visible_through[:10])+'T'+time+'+08:00'
            if time:
                quote={**{key:observation[key] for key in ('limit_up','limit_down','previous_close','no_price_limit','suspended','instrument_name') if key in observation},
                       'symbol':symbol,'price':float(observation['price']),'quote_time':time,'available_at':observation.get('available_at',time),
                       'quote_source':'MARKET_AGENT_OBSERVATION',
                       'freshness':'FRESH'}
        if (not quote or (instant(visible_through)-instant(quote['quote_time'])).total_seconds()>300) and self.fallback:
            quote=self.fallback(symbol) or quote
        if not quote:return None
        if instant(quote['quote_time'])>instant(visible_through) or instant(quote.get('available_at',quote['quote_time']))>instant(visible_through):raise AccountError('FUTURE_QUOTE')
        if (instant(visible_through)-instant(quote['quote_time'])).total_seconds()>300:quote={**quote,'freshness':'STALE'}
        return quote
