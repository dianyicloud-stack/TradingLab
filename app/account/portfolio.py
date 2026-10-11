"""Account application boundary: bind context, source and quotes on the server."""
from datetime import datetime,timezone
from threading import RLock
import json
from engines.account.control import AccountControl
from engines.account.rules import number, validate_policy
from contracts.account.portfolio import AccountError, LIVE_EXECUTION_TRIGGERS
from contracts.system import HealthCheck
from engines.account.ledger import digest, identity


class PortfolioService:
    def __init__(self, engine, quotes, *, namespace='USER', clock=None):
        self.engine,self.quotes,self.namespace=engine,quotes,namespace
        self.clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
        self.advisory_reader=lambda _:None
        self._execution_lock=RLock()
        self.control=AccountControl(engine.repository,namespace)
        engine.repository.control=self.control

    def list(self):
        rows=[x for x in self.engine.repository.list() if x['namespace']==self.namespace]
        # Retained Account-owned provenance excludes historical TEST accounts.
        return [x for x in rows if x['account_type']!='REPLAY_SANDBOX' or
                self._origin(x).get('source',self.namespace)==self.namespace]

    def tracking_references(self,symbol):
        import json
        return ['ACCOUNT:'+a['account_id'] for a in self.list()
                if any(symbol in json.dumps(r,ensure_ascii=False) for r in self.engine.ledger(a['account_id']))]

    def retention_evidence(self,preserve=False):
        """Account-owned self-contained evidence; ledger and projections untouched."""
        import json,hashlib
        refs=set();saved=[]
        def walk(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k=='advisory_id' and isinstance(v,str):refs.add(v)
                    walk(v)
            elif isinstance(value,list):
                for v in value:walk(v)
        with self._execution_lock:
            for account in self.list():
                refs=set();walk(self.engine.ledger(account['account_id']))
                if not preserve:saved.extend(refs);continue
                for identity in sorted(refs):
                    bundle=self.advisory_reader(identity)
                    with self.engine.repository.transaction(account['account_id']) as db:
                        db.execute('CREATE TABLE IF NOT EXISTS retained_advisory_evidence(advisory_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,payload TEXT NOT NULL)')
                        row=db.execute('SELECT sha256,payload FROM retained_advisory_evidence WHERE advisory_id=?',(identity,)).fetchone()
                        if row:
                            if hashlib.sha256(row['payload'].encode()).hexdigest()!=row['sha256']:raise AccountError('RETAINED_EVIDENCE_CORRUPT')
                        else:
                            if not bundle:raise AccountError('ACCOUNT_EVIDENCE_UNAVAILABLE')
                            body=json.dumps({'opinion':bundle[0],'input':bundle[1]},ensure_ascii=False,sort_keys=True)
                            db.execute('INSERT INTO retained_advisory_evidence VALUES(?,?,?)',(identity,hashlib.sha256(body.encode()).hexdigest(),body))
                    saved.append(identity)
        return sorted(set(saved))

    def _origin(self, account):
        from engines.account.retained import read
        return read(self.engine.repository,account['account_id']).get('origin',{})

    def catalog(self):
        return [{**json.loads(r['metadata']),'name':r['name'],'origin':r['origin']} for r in self.control.rows() if r['status']=='ACTIVE']

    def require_account(self, account_id):
        row=next((x for x in self.catalog() if x['account_id']==account_id),None)
        if not row:raise AccountError('ACCOUNT_NOT_FOUND',status=404)
        return row

    def bound(self, account_type, context_id=None):
        binding=self.control.binding()
        if account_type!='LIVE_SHADOW' or context_id or not binding['account_id']:return None
        return self.require_account(binding['account_id'])

    def binding(self):
        with self._execution_lock,self.control.gate():
            b=self.control.binding();account=self.require_account(b['account_id']) if b['account_id'] else None
            if account:
                s=self.engine.state(account['account_id'])
                b.update(name=account['name'],mode=s['policy']['ai_execution_mode'],new_risk_paused=s['new_risk_paused'])
            return {**b,'manual_analysis_eligible':True}

    def bind(self,payload):
        if set(payload)!={'account_id','binding_version'}:raise AccountError('INVALID_BINDING',status=400)
        with self._execution_lock:return self.control.bind(payload['account_id'],payload['binding_version'])

    def create(self,payload):
        allowed={'name','idempotency_key','account_type','initial_capital','policy'}
        if set(payload)-allowed:raise AccountError('UNKNOWN_ACCOUNT_FIELDS',status=400)
        if payload.get('account_type','LIVE_SHADOW')!='LIVE_SHADOW':raise AccountError('RETIRED_ACCOUNT_TYPE')
        name=self.control.name(payload.get('name'));key=payload.get('idempotency_key')
        if not isinstance(key,str) or not 1<=len(key)<=128:raise AccountError('CREATE_REQUEST_ID_REQUIRED',status=400)
        capital=number(payload.get('initial_capital'),.01,200000)
        policy=validate_policy(payload.get('policy',{}));fingerprint=digest(payload)
        with self._execution_lock:
            with self.control.gate() as db:
                old=db.execute('SELECT * FROM creations WHERE namespace=? AND request_key=?',(self.namespace,key)).fetchone()
                if old and old['hash']!=fingerprint:raise AccountError('CREATE_REQUEST_CONFLICT')
                account_id=old['account_id'] if old else identity('AC')
                if not old:db.execute('INSERT INTO creations VALUES(?,?,?,?)',(self.namespace,key,fingerprint,account_id))
            with self.control.gate() as db:
                if self.control.deleted(account_id):raise AccountError('ACCOUNT_DELETED')
                if self.engine.repository.path(account_id).exists():
                    # Recover a creation interrupted after its immutable first event.
                    with self.engine.repository.transaction(account_id) as adb:
                        if self.engine.repository.projection(adb) is None:self.engine._save(adb)
                    state=self.engine.state(account_id)
                else:state=self.engine.create({'account_type':'LIVE_SHADOW','initial_capital':capital,'policy':policy},self.namespace,account_id=account_id)
                meta={k:state[k] for k in ('account_id','account_type','account_generation','context_id','created_at','initial_capital','namespace','parent_account_id','status')}
                db.execute('INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?)',(account_id,self.namespace,name,'USER_CREATED','ACTIVE',json.dumps(meta)))
            return {**state,'name':name}

    def settings(self,account_id,payload):
        if set(payload)-{'name','policy','new_risk_paused','account_state_version'} or 'account_state_version' not in payload:raise AccountError('INVALID_ACCOUNT_SETTINGS',status=400)
        with self._execution_lock,self.control.gate():
            self.require_account(account_id);state=self.engine.state(account_id)
            if payload['account_state_version']!=state['account_state_version']:raise AccountError('ACCOUNT_STATE_CHANGED')
            # Validate all fields before making any change.
            if 'name' in payload:self.control.name(payload['name'])
            if 'policy' in payload:validate_policy(payload['policy'])
            if 'new_risk_paused' in payload and type(payload['new_risk_paused']) is not bool:raise AccountError('INVALID_PAUSE')
            if 'policy' in payload:self.engine.policy(account_id,payload['policy'])
            if 'new_risk_paused' in payload:self.engine.pause(account_id,payload['new_risk_paused'])
            if 'name' in payload:self.control.rename(account_id,payload['name'])
        return self.state(account_id,refresh=False)

    def delete(self,account_id,payload):
        if payload!={'confirmed':True}:raise AccountError('CONFIRM_REQUIRED')
        with self._execution_lock:return self.control.delete(account_id)

    def state(self, account_id, refresh=True):
        with self._execution_lock:
            meta=self.require_account(account_id)
            if meta['account_type']!='LIVE_SHADOW':return {**self.engine.state(account_id),'context_status':'ARCHIVED','read_only':True}
            time=self.quotes.clock(meta,self.clock())
            state=self.engine.state(account_id,time)
            if refresh:
                quotes=[self.quotes.quote(meta,symbol,time) for symbol in state['positions']]
                state=self.engine.observe(account_id,[q for q in quotes if q],time)
            with self.engine.repository.transaction(account_id) as db:
                table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='advisory_results'").fetchone()
                suggestions=[json.loads(r[0]) for r in db.execute('SELECT body FROM advisory_results ORDER BY seq DESC LIMIT 30')] if table else []
            return {**state,'name':meta['name'],'recent_suggestions':suggestions}

    def context(self, symbol, account_type='LIVE_SHADOW', context_id=None, *, refresh=True):
        with self._execution_lock,self.control.gate():
            return self._context(symbol,account_type,context_id,refresh=refresh)

    def _context(self, symbol, account_type='LIVE_SHADOW', context_id=None, *, refresh=True):
        try:account=self.bound(account_type,context_id)
        except AccountError as error:return {'status':'ACCOUNT_ERROR','reason':error.code,'ai_execution_paused':True,'reconciliation_status':'RECONCILIATION_REQUIRED'}
        if not account:return {'status':'NOT_INITIALIZED','reason':'NO_EXECUTION_ACCOUNT','account_type':account_type,'ai_execution_mode':'ADVISORY_ONLY',**self.control.binding()}
        try:
            self.state(account['account_id'],refresh=refresh);time=self.quotes.clock(account,self.clock())
            return {**self.engine.context(account['account_id'],symbol,time),**self.control.binding(),'name':account['name'],'namespace':self.namespace,'manual_analysis_eligible':True}
        except AccountError as error:
            return {'account_id':account['account_id'],'account_type':account_type,'status':'ACCOUNT_ERROR','reason':error.code,
                    'ai_execution_paused':True,'reconciliation_status':'RECONCILIATION_REQUIRED'}

    def manual(self, account_id, payload):
        allowed={'symbol','portfolio_action','target_weight','delta_weight','qty','reason','invalidation','idempotency_key','confirmed'}
        if set(payload)-allowed:raise AccountError('UNKNOWN_INTENT_FIELDS',status=400)
        if payload.get('confirmed') is not True:raise AccountError('CONFIRM_REQUIRED')
        if not payload.get('reason') or not payload.get('idempotency_key'):raise AccountError('AUDIT_REASON_REQUIRED')
        meta=self.require_account(account_id)
        if meta['account_type']!='LIVE_SHADOW':raise AccountError('MANUAL_LIVE_CONTEXT_REQUIRED')
        return self.submit(account_id,{**payload,'source':'LIVE_MANUAL','source_ref':payload['idempotency_key']})

    def submit(self, account_id, intent):
        with self._execution_lock,self.control.gate():
            meta=self.require_account(account_id)
            if meta['account_type']!='LIVE_SHADOW':raise AccountError('ACCOUNT_READ_ONLY')
            self.state(account_id)
            time=self.quotes.clock(meta,self.clock())
            quote=self.quotes.quote(meta,intent['symbol'],time)
            return self.engine.submit(account_id,intent,quote,time)

    def preview(self, account_id, payload):
        allowed={'symbol','portfolio_action','target_weight','delta_weight','qty','reason','invalidation','idempotency_key'}
        if set(payload)-allowed:raise AccountError('UNKNOWN_INTENT_FIELDS')
        account=self.require_account(account_id)
        if account['account_type']!='LIVE_SHADOW':raise AccountError('MANUAL_LIVE_CONTEXT_REQUIRED')
        state=self.state(account_id);time=self.quotes.clock(account,self.clock());quote=self.quotes.quote(account,payload['symbol'],time)
        from engines.account.rules import instant,TZ
        intent={**payload,'source':'LIVE_MANUAL','account_id':account_id,'trade_date':instant(time).astimezone(TZ).date().isoformat(),'market_time':time}
        return self.engine.preview(account_id,intent,quote,time)

    def on_advisory(self, opinion, frozen, confirmed=False):
        with self._execution_lock,self.control.gate():
            result=self._on_advisory(opinion,frozen,confirmed)
            account_id=frozen.get('portfolio_context',{}).get('account_id')
            if (account_id and account_id==self.control.binding()['account_id']
                    and frozen.get('source_namespace')==self.namespace and opinion.get('runtime_mode','LIVE')=='LIVE'
                    and result.get('reason') not in ('ACCOUNT_BINDING_CHANGED','ACCOUNT_NAMESPACE_MISMATCH','MARKET_EVIDENCE_INCOMPLETE')):
                # A small self-contained explanation, not a copy of all AI inputs.
                body={'advisory_id':opinion['advisory_id'],'symbol':opinion['symbol'],
                    'generated_at':opinion.get('generated_at'),'plan':opinion.get('portfolio_plan'),'result':result}
                with self.engine.repository.transaction(account_id) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS advisory_results(seq INTEGER PRIMARY KEY, hash TEXT UNIQUE, body TEXT NOT NULL)')
                    db.execute('INSERT OR IGNORE INTO advisory_results(hash,body) VALUES(?,?)',(digest(body),json.dumps(body,ensure_ascii=False)))
            return result

    def _on_advisory(self, opinion, frozen, confirmed=False):
        with self._execution_lock,self.control.gate():
            if opinion.get('effective_result') is False:
                return {'status':'DEFERRED','reason':'SUPERSEDED_ANALYSIS'}
            if opinion.get('runtime_mode','LIVE')!='LIVE' or opinion.get('trigger_type') not in LIVE_EXECUTION_TRIGGERS:return {'status':'IGNORED','reason':'NON_LIVE_OPINION'}
            account=self.bound('LIVE_SHADOW')
            if not account:return {'status':'NOT_INITIALIZED','reason':'NO_EXECUTION_ACCOUNT'}
            frozen_account=frozen.get('portfolio_context',{}).get('account_id')
            if frozen_account!=account['account_id'] or frozen.get('portfolio_context',{}).get('binding_version')!=self.control.binding()['binding_version']:return {'status':'DEFERRED','reason':'ACCOUNT_BINDING_CHANGED'}
            try:state=self.engine.state(account['account_id'])
            except AccountError as error:return {'status':'FAILED','reason':error.code}
            context=frozen.get('portfolio_context',{})
            if frozen.get('source_namespace')!=self.namespace:return {'status':'BLOCKED','reason':'ACCOUNT_NAMESPACE_MISMATCH'}
            if frozen.get('analysis_mode') or opinion.get('analysis_mode') or frozen.get('data_completeness')=='LIMITED_EVIDENCE':return {'status':'BLOCKED','reason':'MARKET_EVIDENCE_INCOMPLETE'}
            # A repeated success callback returns the recorded result without another order.
            prior=next((e for e in state['executions'] if e.get('advisory_id')==opinion['advisory_id']),None)
            if prior:return {**prior,'duplicate':True}
            if context.get('account_state_version')!=state['account_state_version'] or context.get('policy_version')!=state['policy_version']:return {'status':'BLOCKED','reason':'ACCOUNT_STATE_CHANGED'}
            mode=state['policy']['ai_execution_mode']
            plan=opinion.get('portfolio_plan')
            if mode=='OFF':return {'status':'OFF'}
            if not plan:return {'status':'NEEDS_SIZING','reason':'NEEDS_SIZING'}
            if plan.get('portfolio_action') in ('NONE','HOLD'):
                target=plan.get('target_weight')
                weight=state['positions'].get(opinion['symbol'],{}).get('weight',0)
                if target is not None and (weight is None or abs(target-weight)>.0001):return {'status':'BLOCKED','reason':'ACTION_TARGET_CONFLICT'}
                return {'status':'NO_ACTION','reason':'NO_EXECUTION_ACTION'}
            if not confirmed and mode!='AUTO_SHADOW_EXECUTION':return {'status':'WAITING_HUMAN_CONFIRMATION','portfolio_plan':plan}
            intent={**plan,'symbol':opinion['symbol'],'source':'LIVE_AI_CONFIRMED' if confirmed else 'LIVE_AI_AUTO',
                    'source_ref':opinion['advisory_id'],'advisory_id':opinion['advisory_id'],
                    'advisory_session_date':opinion['session_date'],
                    'frozen_input_hash':frozen['input_hash'],'reason':plan.get('reason') or opinion['core_conflict'],
                    'invalidation':opinion.get('invalidation'),'confidence':opinion.get('confidence')}
            try:return self.submit(account['account_id'],intent)
            except AccountError as error:return {'status':'DEFERRED','reason':error.code}

    def confirm_advisory(self, account_id, advisory_id, payload):
        if payload!={'confirmed':True}:raise AccountError('CONFIRM_REQUIRED')
        account=self.require_account(account_id);bundle=self.advisory_reader(advisory_id)
        if not bundle:raise AccountError('ADVISORY_NOT_FOUND')
        opinion,frozen=bundle
        expected=self.bound('LIVE_SHADOW') if opinion.get('runtime_mode','LIVE')=='LIVE' else None
        if not expected or expected['account_id']!=account_id:raise AccountError('ACCOUNT_CONTEXT_MISMATCH')
        return self.on_advisory(opinion,frozen,True)

    def health(self):
        try:
            states=[self.engine.state(x['account_id']) for x in self.list()]
            bad=any(s['reconciliation_status']=='RECONCILIATION_REQUIRED' for s in states)
            return HealthCheck('account_stores','Unified Shadow Account','ERROR' if bad else 'READY','Account-owned immutable ledgers · isolated contexts')
        except (AccountError,ValueError):return HealthCheck('account_stores','Unified Shadow Account','ERROR','Account ledger requires audit')
