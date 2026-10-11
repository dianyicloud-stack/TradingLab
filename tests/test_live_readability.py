"""Saved-opinion display reads stay bounded and never load market facts."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest
from tests.support.native import NativeFixture

ROOT=Path(__file__).resolve().parents[1]


class HistoryDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix='reading-display-',dir=ROOT/'tests')
        self.addCleanup(self.tmp.cleanup)
        self.f=NativeFixture(Path(self.tmp.name));self.addCleanup(self.f.close)
        self.a=self.f.advisory;self.a.market_is_open=lambda _:True
        self.f.append();self.first=self.a.analyze('bj920161')
        self.f.append(price=11);self.second=self.a.analyze('bj920161')
        self.router=next(r for r in self.f.app.routers if type(r).__name__=='LiveRouter')
        self.cached={'advisory_cards':[{'session':{'symbol':s,'tracking_session_id':m['tracking_session_id']}} for s,m in self.f.members.items()]}
        self.router.read_model=Mock(read=lambda:deepcopy(self.cached))

    def read(self,kind='history',symbol='bj920161',query=None):
        return self.router.route('GET',f'/api/live/{symbol}/advisory/{kind}',query)

    def test_history_uses_saved_facts_even_if_market_reader_is_blocked(self):
        with patch.object(self.a,'_member',side_effect=AssertionError('must not fetch market')):
            status,value,_=self.read()
        self.assertEqual(status,200)
        self.assertEqual([x['advisory_id'] for x in value['opinions']],[self.second['advisory_id'],self.first['advisory_id']])

    def test_timeline_has_real_ordered_saved_opinions(self):
        with patch.object(self.a,'_member',side_effect=AssertionError('must not fetch market')):
            _,value,_=self.read('timeline')
        self.assertEqual([x['advisory_id'] for x in value['timeline']],[self.first['advisory_id'],self.second['advisory_id']])

    def test_empty_stock_never_borrows_other_history(self):
        _,value,_=self.read(symbol='sh688696')
        self.assertEqual(value['opinions'],[]);self.assertEqual(value['availability'],'READY')

    def test_old_session_request_cannot_render_new_session_history(self):
        _,value,_=self.read(query={'tracking_session_id':'old-session'})
        self.assertEqual(value['opinions'],[]);self.assertEqual(value['availability'],'SESSION_CHANGED')

    def test_cold_read_model_has_explicit_availability(self):
        self.cached['advisory_cards']=[]
        with patch.object(self.a,'_member',side_effect=AssertionError('must not fetch market')):
            _,value,_=self.read()
        self.assertEqual(value['availability'],'WAITING_CURRENT_SESSION');self.assertTrue(value['message'])

    def test_limit_validation_and_no_writes(self):
        cursor=self.a.runtime.cursor(self.first['tracking_session_id']);calls=len(self.f.provider.calls)
        self.assertEqual(len(self.read(query={'limit':'1'})[1]['opinions']),1)
        self.assertEqual(self.read(query={'limit':'invalid'})[0],400)
        self.assertEqual(self.a.runtime.cursor(self.first['tracking_session_id']),cursor)
        self.assertEqual(len(self.f.provider.calls),calls)
        self.assertEqual(self.a.by_id(self.first['advisory_id']),self.first)


if __name__=='__main__':unittest.main()
