"""Small test-only clock-bounded fact source. No product session/service/HTTP API."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from contracts.live.bridge import BridgeError

def _parse(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))

class ClockedFacts:
    def __init__(self,dataset,clock):self.dataset,self.clock=deepcopy(dataset),clock
    def connected(self):return True
    def _visible(self):
        cutoff=self.clock()
        return [deepcopy(x) for x in self.dataset['facts'] if _parse(x['timestamp'])<=cutoff and
                _parse(x.get('available_at') or x.get('payload',{}).get('available_at') or x['timestamp'])<=cutoff]
    def sessions(self):return self.snapshot()['sessions']
    def _session(self,identity):
        row=next((x for x in self.dataset['sessions'] if x.get('tracking_session_id')==identity),None)
        if not row:raise BridgeError('LIVE_SESSION_NOT_FOUND',status=404)
        return row
    def events(self,identity):
        self._session(identity);return [x['payload'] for x in self._visible() if x['kind']=='EVENT' and x['tracking_session_id']==identity]
    def latest_observation(self,identity):
        member=self._session(identity);rows=[x for x in self._visible() if x['kind']=='OBSERVATION' and x['tracking_session_id']==identity]
        if not rows:return {}
        row=deepcopy(rows[-1]['payload']);row.update(tracking_session_id=identity,symbol=member['symbol'],last_observation_time=rows[-1]['timestamp']);return row
    def advisory_facts(self,symbol):
        session=next((x for x in self.sessions() if x['symbol']==symbol),None)
        if not session:raise BridgeError('LIVE_SYMBOL_NOT_FOUND',status=404)
        identity=session['tracking_session_id']
        observations=[{**x['payload'],'timestamp':x['timestamp']} for x in self._visible() if x['kind']=='OBSERVATION' and x['tracking_session_id']==identity]
        return {'session':session,'events':self.events(identity),'observations':observations,
                'current_state':observations[-1] if observations else {}}
    def snapshot(self):
        visible=self._visible();rows=[]
        for member in self.dataset['sessions']:
            identity=member['tracking_session_id'];events=[x for x in visible if x['kind']=='EVENT' and x['tracking_session_id']==identity];obs=[x for x in visible if x['kind']=='OBSERVATION' and x['tracking_session_id']==identity]
            latest=obs[-1] if obs else None;payload=latest['payload'] if latest else {}
            rows.append({'tracking_session_id':identity,'symbol':member['symbol'],'name':member.get('name') or member['symbol'],'market_date':self.dataset['source_session_date'],'lifecycle':'SIMULATION',
                'last_observation_time':latest['timestamp'] if latest else (events[-1]['timestamp'] if events else None),'price':payload.get('price'),'vwap':payload.get('vwap'),'event_count':len(events),'pending_event_count':len(events),
                'updated_at':self.clock().isoformat()})
        return {'status':'READY','connection':{'kind':'SIMULATION_DATASET','configured':True},'sessions':rows,'updated_at':self.clock().isoformat()}
