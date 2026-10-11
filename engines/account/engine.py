"""One execution engine for every shadow context. No broker or Legacy dependency."""
from copy import deepcopy
from decimal import Decimal
from contracts.account.portfolio import AccountError, ACTIONS, SOURCES, OWNERS
from engines.account.ledger import canonical, digest, identity, stamp
from engines.account.rules import MarketRuleService, amount, number, instant, validate_policy, TZ


class AccountEngine:
    def __init__(self, repository, rules=None):
        self.repository, self.rules = repository, rules or MarketRuleService()

    def create(self, payload, namespace='USER', *, account_id=None):
        allowed={'account_type','initial_capital','policy','context_id','parent_account_id'}
        if set(payload)-allowed: raise AccountError('UNKNOWN_ACCOUNT_FIELDS')
        if payload.get('account_type') not in ('LIVE_SHADOW','REPLAY_SANDBOX','SIMULATION_SANDBOX'):raise AccountError('INVALID_ACCOUNT_TYPE')
        capital=amount(number(payload.get('initial_capital'),.01))
        policy=validate_policy(payload.get('policy',{})); parent=payload.get('parent_account_id'); generation=1
        if parent:
            old=self.state(parent)
            if old['account_type']!=payload['account_type'] or old['namespace']!=namespace or old['context_id']!=payload.get('context_id'): raise AccountError('ACCOUNT_CONTEXT_MISMATCH')
            generation=old['account_generation']+1
        meta=self.repository.create(payload['account_type'],capital,policy,context_id=payload.get('context_id'),generation=generation,parent=parent,namespace=namespace,account_id=account_id)
        with self.repository.transaction(meta['account_id']) as db: self._save(db)
        return self.state(meta['account_id'])

    def _rebuild(self, events):
        if not events: raise AccountError('EMPTY_LEDGER')
        state={**events[0]['account'],'policy':deepcopy(events[0]['policy']),'cash':events[0]['account']['initial_capital'],
               'lots':[],'realized_pnl':0.,'executions':[],'new_symbols':{},'new_exposure':{},'quotes':{},'invalid_executions':[],
               'reconciliation_status':'IN_SYNC','attribution':{},'ownership_attribution':{},'market_time':None}
        voided={x['execution_id'] for x in events if x['event_type']=='TRADE_VOIDED'}
        for event in events[1:]:
            kind=event['event_type']
            if event.get('account_revision'):
                state['account_revision']=event['account_revision']
                if kind=='RISK_POLICY_CHANGED':state['policy_revision']=event['account_revision']
            if kind=='RISK_POLICY_CHANGED': state['policy']=deepcopy(event['policy'])
            elif kind=='NEW_RISK_PAUSE_CHANGED':state['new_risk_paused']=event['paused']
            elif kind=='CLOCK_ADVANCED':state['market_time']=event['market_time']
            elif kind=='QUOTE_OBSERVED':
                state['quotes'][event['quote']['symbol']]=deepcopy(event['quote']); state['market_time']=event['market_time']
            elif kind in ('DRIFT_DETECTED','UNKNOWN_DELTA'): state['reconciliation_status']='RECONCILIATION_REQUIRED'
            elif kind=='RECONCILIATION_COMPLETED': state['reconciliation_status']='RECONCILED'
            elif kind=='OWNERSHIP_CHANGED':
                for lot in state['lots']:
                    if lot['lot_id']==event['lot_id']: lot['ownership']=event['ownership']
            elif kind=='MANUAL_CORRECTION':
                state['cash']=amount(state['cash']+event.get('cash_delta',0))
                if event.get('lot'): state['lots'].append(deepcopy(event['lot']))
            elif kind=='EXECUTION_COMPLETED':
                execution=deepcopy(event['execution']); state['executions'].append(execution)
                if execution['execution_id'] in voided:
                    execution['status']='VOIDED'; continue
                qty=execution['executed_qty']
                if not qty: continue
                allocations=execution.get('allocations',[])
                lots={lot['lot_id']:lot for lot in state['lots']}
                legal=state['cash']+execution['cash_delta']>=-.005
                if execution['side']=='SELL':
                    legal=legal and all(a['lot_id'] in lots and lots[a['lot_id']]['remaining_qty']>=a['qty'] and lots[a['lot_id']]['available_trade_date']<=execution['trade_date'] for a in allocations)
                if not legal:
                    execution['status']='INVALID_AFTER_REBUILD';state['invalid_executions'].append(execution['execution_id']);continue
                symbol=execution['symbol'];before=sum(l['remaining_qty'] for l in state['lots'] if l['symbol']==symbol)
                state['cash']=amount(state['cash']+execution['cash_delta'])
                if execution['side']=='BUY':
                    state['lots'].append(deepcopy(execution['lot']))
                    day=execution['trade_date']; state['new_exposure'][day]=amount(state['new_exposure'].get(day,0)+execution['gross_amount'])
                    if not before: state['new_symbols'].setdefault(day,[]).append(symbol)
                else:
                    cost=0
                    for a in allocations:
                        lot=lots[a['lot_id']];lot['remaining_qty']-=a['qty']; cost+=lot['unit_cost']*a['qty']
                        owner=lot['ownership'];attributed=execution['cash_delta']*a['qty']/qty-lot['unit_cost']*a['qty']
                        state['ownership_attribution'][owner]=amount(state['ownership_attribution'].get(owner,0)+attributed)
                    pnl=amount(execution['cash_delta']-cost);state['realized_pnl']=amount(state['realized_pnl']+pnl)
                    state['attribution'][execution['source']]=amount(state['attribution'].get(execution['source'],0)+pnl)
        return state

    def _save(self, db):
        state=self._rebuild(self.repository.events(db));self.repository.save_projection(db,state);return state

    def _checked(self, db):
        truth=self._rebuild(self.repository.events(db));projection=self.repository.projection(db)
        if projection is None or canonical(truth)!=canonical(projection):
            if truth['reconciliation_status'] not in ('RECONCILIATION_REQUIRED','DRIFT_DETECTED'):
                self.repository.append(db,'UNKNOWN_DELTA',{'account_id':truth['account_id'],'expected':truth,'observed':projection,'reason':'PROJECTION_MISMATCH'})
            truth=self._rebuild(self.repository.events(db))
        return truth

    def state(self, account_id, market_time=None):
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            if state['account_type']!='LIVE_SHADOW' and market_time and state['market_time'] and instant(market_time)<instant(state['market_time']):
                raise AccountError('ACCOUNT_AHEAD_OF_REPLAY')
            return self._view(state,market_time or state['market_time'])

    def _view(self, state, market_time):
        result=deepcopy(state)
        result['account_state_version']=digest({k:v for k,v in state.items() if k not in ('quotes','market_time')})
        result['policy_version']=digest([state['policy'],state.get('policy_revision')])
        result['new_risk_paused']=state.get('new_risk_paused',False)
        day=instant(market_time).astimezone(TZ).date().isoformat() if market_time else ''
        positions={};missing=[]
        for lot in result['lots']:
            qty=lot['remaining_qty']; available=qty if day and day>=lot['available_trade_date'] else 0
            lot.update(available_qty=available,locked_qty=qty-available)
            if not qty:continue
            p=positions.setdefault(lot['symbol'],{'symbol':lot['symbol'],'qty':0,'available_qty':0,'locked_qty':0,'cost_basis':0,'ownership':{}})
            p['qty']+=qty;p['available_qty']+=available;p['locked_qty']+=qty-available;p['cost_basis']+=qty*lot['unit_cost']
            p['ownership'][lot['ownership']]=p['ownership'].get(lot['ownership'],0)+qty
        market_value=0
        for symbol,p in positions.items():
            quote=state['quotes'].get(symbol);price=quote.get('price') if quote else None
            if price is None: missing.append(symbol)
            p.update(avg_cost=p['cost_basis']/p['qty'],latest_price=price,quote=quote,
                     market_value=amount(p['qty']*price) if price is not None else None)
            market_value+=p['market_value'] or 0
            p['unrealized_pnl']=amount(p['market_value']-p['cost_basis']) if price is not None else None
            p['unrealized_pnl_pct']=p['unrealized_pnl']/p['cost_basis'] if p['cost_basis'] and price is not None else None
        equity=amount(state['cash']+market_value) if not missing else None
        for p in positions.values(): p['weight']=p['market_value']/equity if equity else None
        result.update(positions=positions,market_value=amount(market_value) if not missing else None,total_equity=equity,
                      unrealized_pnl=amount(sum(p['unrealized_pnl'] or 0 for p in positions.values())) if not missing else None,
                      total_return=(equity/state['initial_capital']-1) if equity is not None else None,
                      total_exposure=market_value/equity if equity else None,valuation_as_of=market_time,
                      valuation_status='QUOTE_UNAVAILABLE' if missing else 'READY',trade_date=day,
                      new_positions_today=len(set(state['new_symbols'].get(day,[]))),new_exposure_today=state['new_exposure'].get(day,0))
        for e in result['executions']:
            if e['status'] in ('DEFERRED','PARTIALLY_EXECUTED') and e.get('reason')=='T1_LOCK' and day>e['trade_date'] and self.rules.calendar.is_open(day):
                e['reevaluation_status']='READY_FOR_REEVALUATION'
        return result

    def context(self, account_id, symbol, market_time=None):
        state=self.state(account_id,market_time);p=state['positions'].get(symbol,{})
        recent=[{**x,'action':('MANUAL_' if x['source']=='LIVE_MANUAL' else '')+x['portfolio_action'],
                 'price':x['execution_price'],'time':x['market_time']} for x in state['executions'] if x['symbol']==symbol][-10:]
        return {**{k:state[k] for k in ('account_id','account_type','account_generation','account_state_version','policy_version','new_risk_paused','cash','total_equity','policy','total_exposure','new_positions_today','new_exposure_today','reconciliation_status')},
                'current_position_weight':p.get('weight',0),'position_quantity':p.get('qty',0),'average_cost':p.get('avg_cost'),
                'available_quantity':p.get('available_qty',0),'t1_locked_quantity':p.get('locked_qty',0),
                'ownership':p.get('ownership',{}),'recent_account_actions':recent,
                'symbol':symbol,'position_exists':bool(p),'position':p,'open_positions_count':len(state['positions']),
                'recent_actions':recent,
                'available_capacity':max(0,state['policy']['max_position_weight_per_symbol']-(p.get('weight') or 0)),
                'bought_today':sum(x['executed_qty'] for x in state['executions'] if x['symbol']==symbol and x['trade_date']==state['trade_date'] and x['side']=='BUY' and x['status'] in ('EXECUTED','PARTIALLY_EXECUTED')),
                'sold_today':sum(x['executed_qty'] for x in state['executions'] if x['symbol']==symbol and x['trade_date']==state['trade_date'] and x['side']=='SELL' and x['status'] in ('EXECUTED','PARTIALLY_EXECUTED')),
                'ai_execution_paused':state['reconciliation_status']=='RECONCILIATION_REQUIRED'}

    def pause(self, account_id, paused):
        if type(paused) is not bool:raise AccountError('INVALID_PAUSE',status=400)
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            if state.get('new_risk_paused',False)!=paused:
                self.repository.append(db,'NEW_RISK_PAUSE_CHANGED',{'account_id':account_id,'paused':paused,'account_revision':identity('REV')});self._save(db)
        return self.state(account_id)

    def policy(self, account_id, payload):
        policy=validate_policy(payload)
        with self.repository.transaction(account_id) as db:
            if self._checked(db)['reconciliation_status']=='RECONCILIATION_REQUIRED':raise AccountError('RECONCILIATION_REQUIRED')
            self.repository.append(db,'RISK_POLICY_CHANGED',{'account_id':account_id,'policy':policy,'account_revision':identity('REV')});self._save(db)
        return self.state(account_id)

    def observe(self, account_id, quotes, market_time):
        cutoff=instant(market_time)
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            if state['reconciliation_status']=='RECONCILIATION_REQUIRED':return self._view(state,market_time)
            if state['market_time'] and cutoff<instant(state['market_time']):raise AccountError('ACCOUNT_AHEAD_OF_REPLAY')
            if state['market_time']!=market_time:self.repository.append(db,'CLOCK_ADVANCED',{'account_id':account_id,'market_time':market_time})
            for quote in quotes:
                if instant(quote['quote_time'])>cutoff or instant(quote.get('available_at',quote['quote_time']))>cutoff:raise AccountError('FUTURE_QUOTE')
                number(quote['price'],.0001);self.rules.rule(quote['symbol'])
                if state['quotes'].get(quote['symbol'])!=quote:self.repository.append(db,'QUOTE_OBSERVED',{'account_id':account_id,'quote':quote,'market_time':market_time})
            return self._view(self._save(db),market_time)

    def submit(self, account_id, intent, quote, market_time):
        """Trusted domain entry. API supplies identity/reason/sizing only; source/quote/clock are injected."""
        action=intent.get('portfolio_action');source=intent.get('source');symbol=intent.get('symbol')
        if action not in ACTIONS or source not in SOURCES:raise AccountError('INVALID_INTENT')
        self.rules.rule(symbol);time=instant(market_time);day=time.astimezone(TZ).date().isoformat()
        for key in ('target_weight','delta_weight'):
            if intent.get(key) is not None:number(intent[key],0,1)
        if intent.get('qty') is not None:
            if type(intent['qty']) is not int or intent['qty']<=0:raise AccountError('INVALID_QTY')
        if sum(intent.get(k) is not None for k in ('target_weight','delta_weight','qty'))>1:raise AccountError('AMBIGUOUS_SIZING')
        key=digest([account_id,'LIVE_AI' if source.startswith('LIVE_AI') else source,intent.get('source_ref'),symbol,action,intent.get('target_weight'),intent.get('delta_weight'),intent.get('qty'),intent.get('frozen_input_hash'),intent.get('idempotency_key')])
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            for old in state['executions']:
                if old['request_fingerprint']==key:return {**old,'duplicate':True}
            expected={'LIVE_SHADOW':{'LIVE_AI_AUTO','LIVE_AI_CONFIRMED','LIVE_MANUAL'},'REPLAY_SANDBOX':{'LEARNING','REPLAY'},'SIMULATION_SANDBOX':{'SIMULATION'}}[state['account_type']]
            if source not in expected:raise AccountError('ACCOUNT_CONTEXT_MISMATCH')
            if state['market_time'] and time<instant(state['market_time']):raise AccountError('ACCOUNT_AHEAD_OF_REPLAY')
            value={**{key:None for key in ('signal_price','confidence','invalidation','advisory_id','case_id','replay_session_id','simulation_session_id','frozen_input_hash','target_weight','delta_weight','qty')},
                   **deepcopy(intent),'intent_id':identity('PI'),'account_id':account_id,'account_type':state['account_type'],'market':symbol[:2].upper(),
                   'market_time':market_time,'trade_date':day,'created_at':stamp(),'request_fingerprint':key,
                   'portfolio_state_changed_id':identity('PSC')}
            self.repository.append(db,'INTENT_CREATED',{'account_id':account_id,'intent':value})
            self.repository.append(db,'EXECUTION_STATE_CHANGED',{'account_id':account_id,'intent_id':value['intent_id'],'status':'CREATED'})
            view=self._view(state,market_time)
            result=self._policy_execute(view,value,quote,market_time)
            self.repository.append(db,'ORDER_CREATED',{'account_id':account_id,'order_id':result['order_id'],'intent_id':value['intent_id']})
            if result['executed_qty']:
                self.repository.append(db,'EXECUTION_STATE_CHANGED',{'account_id':account_id,'intent_id':value['intent_id'],'execution_id':result['execution_id'],'status':'READY'})
            elif result['status']=='DEFERRED':
                self.repository.append(db,'EXECUTION_DEFERRED',{'account_id':account_id,'intent_id':value['intent_id'],'execution_id':result['execution_id'],'reason':result['reason']})
            if quote and result['reason'] not in ('FUTURE_QUOTE','STALE_QUOTE','QUOTE_UNAVAILABLE'):
                self.repository.append(db,'QUOTE_OBSERVED',{'account_id':account_id,'quote':quote,'market_time':market_time})
            self.repository.append(db,'EXECUTION_COMPLETED',{'account_id':account_id,'execution':result})
            if result['executed_qty']:self.repository.append(db,'FILL_RECORDED',{'account_id':account_id,'execution_id':result['execution_id'],'qty':result['executed_qty'],'price':result['execution_price'],'fees':result['fees'],'trade_date':day})
            if state['reconciliation_status']!='RECONCILIATION_REQUIRED':
                projected=self._view(self._save(db),market_time);position=projected['positions'].get(symbol,{})
                self.repository.append(db,'PORTFOLIO_STATE_CHANGED',{'account_id':account_id,'symbol':symbol,'cash':projected['cash'],
                    'portfolio_state_changed_id':value['portfolio_state_changed_id'],'advisory_id':value.get('advisory_id'),
                    'intent_id':value['intent_id'],'execution_id':result['execution_id'],
                    'equity':projected['total_equity'],'position_qty':position.get('qty',0),'available_qty':position.get('available_qty',0),
                    'locked_qty':position.get('locked_qty',0),'current_weight':position.get('weight',0),'ownership':position.get('ownership',{}),
                    'last_action':action,'execution_status':result['status'],'updated_at':market_time,'source':source})
            return result

    def _policy_execute(self, state, intent, quote, market_time):
        symbol,action,source=intent['symbol'],intent['portfolio_action'],intent['source'];day=intent['trade_date'];policy=state['policy']
        result={**intent,'intent_reason':intent.get('reason'),'execution_id':identity('EX'),'order_id':identity('OR'),'status':'POLICY_REJECTED','reason':None,
                'requested_qty':0,'executed_qty':0,'blocked_qty':0,'signal_price':intent.get('signal_price'),
                'reference_price':quote.get('price') if quote else None,'execution_price':None,'gross_amount':0,'fees':{'total':0},'cash_delta':0,
                'side':'BUY' if action in ('OPEN','ADD') else 'SELL','allocations':[],'duplicate':False}
        def stop(reason,status='POLICY_REJECTED'):
            result.update(reason=reason,status=status,blocked_qty=result['requested_qty']-result['executed_qty']);return result
        if state['reconciliation_status']=='RECONCILIATION_REQUIRED':return stop('RECONCILIATION_REQUIRED')
        if source.startswith('LIVE_AI'):
            if policy['ai_execution_mode']=='OFF':return stop('AI_EXECUTION_OFF')
            if source=='LIVE_AI_AUTO' and policy['ai_execution_mode']!='AUTO_SHADOW_EXECUTION':return stop('HUMAN_CONFIRMATION_REQUIRED')
        if action in ('OPEN','ADD') and state.get('new_risk_paused'):return stop('NEW_RISK_PAUSED')
        if action=='EXIT' and intent.get('target_weight') not in (None,0):return stop('ACTION_TARGET_CONFLICT')
        if action in ('NONE','HOLD'):return stop('NO_EXECUTION_ACTION','EXECUTED')
        if intent.get('advisory_session_date') and intent['advisory_session_date']!=day:return stop('READY_FOR_REEVALUATION','DEFERRED')
        if not any(intent.get(k) is not None for k in ('target_weight','delta_weight','qty')) and action!='EXIT':return stop('NEEDS_SIZING','DEFERRED')
        if quote is None:return stop('QUOTE_UNAVAILABLE','DEFERRED')
        if quote.get('symbol')!=symbol:return stop('QUOTE_SYMBOL_MISMATCH')
        if instant(quote['quote_time'])>instant(market_time) or instant(quote.get('available_at',quote['quote_time']))>instant(market_time):return stop('FUTURE_QUOTE')
        if (instant(market_time)-instant(quote['quote_time'])).total_seconds()>300 or quote.get('freshness') not in ('FRESH','REPLAY_VISIBLE','SIMULATION_VISIBLE'):return stop('STALE_QUOTE','DEFERRED')
        if not self.rules.session(market_time):return stop('TRADING_SESSION','DEFERRED')
        if quote.get('suspended'):return stop('MARKET_NOT_AVAILABLE','DEFERRED')
        if 'ST' in str(quote.get('instrument_name','')).upper():return stop('SPECIAL_INSTRUMENT_RULES_UNAVAILABLE','DEFERRED')
        reference=number(quote['price'],.0001);side=result['side'];price=amount(Decimal(str(reference))*(1+Decimal(str(policy['slippage_model']['bps']))/10000*(1 if side=='BUY' else -1)))
        if price<=0:return stop('INVALID_EXECUTION_PRICE')
        if quote.get('previous_close') and not quote.get('no_price_limit'):
            limit=self.rules.rule(symbol)['ordinary_price_limit']
            quote={**quote,'limit_up':quote.get('limit_up',amount(quote['previous_close']*(1+limit))),
                   'limit_down':quote.get('limit_down',amount(quote['previous_close']*(1-limit)))}
        if quote.get('limit_up') is not None and side=='BUY' and price>=quote['limit_up']:return stop('PRICE_LIMIT','DEFERRED')
        if quote.get('limit_down') is not None and side=='SELL' and price<=quote['limit_down']:return stop('PRICE_LIMIT','DEFERRED')
        # Revalue the target using the current execution quote, without adding future data.
        positions=state['positions'];p=positions.get(symbol,{});held=p.get('qty',0)
        if (action=='OPEN' and held) or (action=='ADD' and not held):return stop('ACTION_POSITION_CONFLICT')
        if any(x!=symbol and (not positions[x]['quote'] or positions[x]['quote'].get('freshness') not in ('FRESH','REPLAY_VISIBLE','SIMULATION_VISIBLE') or
               (instant(market_time)-instant(positions[x]['quote']['quote_time'])).total_seconds()>300) for x in positions):return stop('STALE_PORTFOLIO_QUOTE','DEFERRED')
        if state['total_equity'] is None:return stop('QUOTE_UNAVAILABLE','DEFERRED')
        old_mv=p.get('market_value') or 0;equity=state['total_equity']-old_mv+held*reference;mv=(state['market_value'] or 0)-old_mv+held*reference
        if action=='EXIT':raw=held
        elif intent.get('qty') is not None:raw=intent['qty']
        elif intent.get('target_weight') is not None:
            difference=equity*intent['target_weight']-held*reference
            if (side=='BUY' and difference<0) or (side=='SELL' and difference>0):return stop('ACTION_TARGET_CONFLICT')
            if difference==0:return stop('TARGET_ALREADY_REACHED','EXECUTED')
            raw=int(abs(difference)/price)
        else:raw=int(equity*intent['delta_weight']/price)
        requested=self.rules.round_qty(symbol,raw,sell=side=='SELL',available=held);result['requested_qty']=requested
        if not requested:return stop('MINIMUM_LOT')
        qty=requested;reason=None
        if side=='BUY':
            if not held and len(positions)>=policy['max_open_positions']:return stop('MAX_OPEN_POSITIONS')
            if not held and symbol not in state['new_symbols'].get(day,[]) and state['new_positions_today']>=policy['max_new_positions_per_day']:return stop('MAX_NEW_POSITIONS_PER_DAY')
            caps=[(equity*policy['max_position_weight_per_symbol']-held*reference,'POSITION_LIMIT'),
                  (equity*policy['max_total_exposure_pct']-mv,'MAX_TOTAL_EXPOSURE'),
                  (equity*policy['max_new_exposure_per_day_pct']-state['new_exposure_today'],'MAX_NEW_EXPOSURE_PER_DAY'),
                  (state['cash']-equity*policy['minimum_cash_reserve_pct'],'MINIMUM_CASH_RESERVE')]
            cap,cap_reason=min(caps)
            if qty*price>cap:qty=self.rules.round_qty(symbol,max(0,int(cap/price)));reason=cap_reason
            # Account-wide cash/reserve check includes fees and slippage inside this transaction.
            step=self.rules.rule(symbol)['increment']
            while qty:
                fee=self.rules.fees(qty*price,side,policy['fee_model'])['total']
                after_equity=equity-fee-qty*(price-reference)
                limits=[((held+qty)*reference<=after_equity*policy['max_position_weight_per_symbol']+.0001,'POSITION_LIMIT'),
                        (mv+qty*reference<=after_equity*policy['max_total_exposure_pct']+.0001,'MAX_TOTAL_EXPOSURE'),
                        (state['new_exposure_today']+qty*price<=after_equity*policy['max_new_exposure_per_day_pct']+.0001,'MAX_NEW_EXPOSURE_PER_DAY'),
                        (state['cash']-qty*price-fee>=after_equity*policy['minimum_cash_reserve_pct']-.0001,'MINIMUM_CASH_RESERVE')]
                violation=next((label for valid,label in limits if not valid),None)
                if not violation:break
                qty=self.rules.round_qty(symbol,qty-step);reason=violation
            if not qty:return stop(reason or cap_reason)
        else:
            lots=[l for l in state['lots'] if l['symbol']==symbol and l['remaining_qty'] and (not source.startswith('LIVE_AI') or l['ownership']=='AI_MANAGED')]
            owned=sum(l['remaining_qty'] for l in lots);available=sum(l['available_qty'] for l in lots)
            if not owned:return stop('MANUAL_PROTECTED' if held else 'NO_POSITION')
            qty=min(qty,available)
            if qty<requested:reason='T1_LOCK' if available<min(owned,requested) else 'MANUAL_PROTECTED'
            qty=self.rules.round_qty(symbol,qty,sell=True,available=available)
            if not qty:return stop(reason or 'T1_LOCK','DEFERRED')
            remaining=qty
            for lot in lots:
                used=min(remaining,lot['available_qty'])
                if used:result['allocations'].append({'lot_id':lot['lot_id'],'qty':used});remaining-=used
        gross=amount(qty*price);fees=self.rules.fees(gross,side,policy['fee_model'])
        result.update(status='PARTIALLY_EXECUTED' if qty<requested else 'EXECUTED',reason=reason,executed_qty=qty,blocked_qty=requested-qty,
                      execution_price=price,gross_amount=gross,fees=fees,cash_delta=amount(-gross-fees['total'] if side=='BUY' else gross-fees['total']))
        if side=='BUY':
            owner='AI_MANAGED' if source.startswith('LIVE_AI') else 'MANUAL_PROTECTED' if source=='LIVE_MANUAL' else source
            result['lot']={'lot_id':identity('LOT'),'symbol':symbol,'trade_date':day,'qty':qty,'remaining_qty':qty,
                           'available_trade_date':self.rules.calendar.next_day(day),'source':source,'ownership':owner,
                           'execution_id':result['execution_id'],'unit_cost':(gross+fees['total'])/qty}
        return result

    def preview(self, account_id, intent, quote, market_time):
        if intent.get('portfolio_action') not in ACTIONS:raise AccountError('INVALID_INTENT')
        if intent.get('qty') is not None and (type(intent['qty']) is not int or intent['qty']<=0):raise AccountError('INVALID_QTY')
        for key in ('target_weight','delta_weight'):
            if intent.get(key) is not None:number(intent[key],0,1)
        if sum(intent.get(k) is not None for k in ('target_weight','delta_weight','qty'))>1:raise AccountError('AMBIGUOUS_SIZING')
        self.rules.rule(intent.get('symbol'))
        with self.repository.transaction(account_id) as db:
            return self._policy_execute(self._view(self._checked(db),market_time),intent,quote,market_time)

    def void(self, account_id, execution_id, reason, user):
        if not reason or not user:raise AccountError('AUDIT_REASON_REQUIRED')
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            target=next((x for x in state['executions'] if x['execution_id']==execution_id),None)
            if state['reconciliation_status']=='RECONCILIATION_REQUIRED':raise AccountError('RECONCILIATION_REQUIRED')
            if not target:raise AccountError('EXECUTION_NOT_FOUND')
            if target['status']=='VOIDED':return self._view(state,state['market_time'])
            self.repository.append(db,'TRADE_VOIDED',{'account_id':account_id,'execution_id':execution_id,'reason':reason,'user':user})
            rebuilt=self._save(db)
            for invalid in rebuilt['invalid_executions']:
                self.repository.append(db,'INVALID_AFTER_REBUILD',{'account_id':account_id,'execution_id':invalid,'reason':'DEPENDENCY_VOIDED'})
            return self._view(rebuilt,rebuilt['market_time'])

    def ownership(self, account_id, lot_id, owner, reason, user):
        if owner not in OWNERS or not user or not reason:raise AccountError('OWNERSHIP_CONFIRM_REQUIRED')
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            if not any(x['lot_id']==lot_id for x in state['lots']):raise AccountError('LOT_NOT_FOUND')
            if state['reconciliation_status']=='RECONCILIATION_REQUIRED':raise AccountError('RECONCILIATION_REQUIRED')
            self.repository.append(db,'OWNERSHIP_CHANGED',{'account_id':account_id,'lot_id':lot_id,'ownership':owner,'reason':reason,'user':user});self._save(db)
        return self.state(account_id)

    def reconcile(self, account_id, mode, reason, user, correction=None):
        if mode not in ('REBUILD_FROM_LEDGER','MANUAL_CORRECTION') or not reason or not user:raise AccountError('RECONCILIATION_CONFIRM_REQUIRED')
        with self.repository.transaction(account_id) as db:
            state=self._checked(db)
            if mode=='MANUAL_CORRECTION':
                correction=deepcopy(correction or {});delta=correction.get('cash_delta',0)
                number(abs(delta));lot=correction.get('lot')
                if state['cash']+delta<0:raise AccountError('NEGATIVE_CASH')
                if lot:
                    self.rules.rule(lot['symbol']);number(lot['qty'],1);number(lot['unit_cost'],.0001)
                    lot.update(lot_id=identity('LOT'),ownership='MANUAL_PROTECTED',source='LIVE_MANUAL',remaining_qty=lot['qty'],execution_id=None,
                               available_trade_date=self.rules.calendar.next_day(lot['trade_date']))
                self.repository.append(db,'MANUAL_CORRECTION',{'account_id':account_id,'cash_delta':delta,'lot':lot,'reason':reason,'user':user})
            self.repository.append(db,'RECONCILIATION_COMPLETED',{'account_id':account_id,'mode':mode,'reason':reason,'user':user})
            self._save(db)
        return self.state(account_id)

    def ledger(self, account_id):
        with self.repository.transaction(account_id) as db:return self.repository.events(db)
