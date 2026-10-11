"""Detached TEST process: real Agent core, HTTP enable, Listener and success callback."""
from pathlib import Path
import sys,json,threading,time
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.agent_auto_fixture import AgentAutoFixture
from tests.test_telegram_notifications import FakeSender
from app.system.notifications import Notifications
from adapters.telegram import TelegramConfig
from shared.config import ScopedStore
from app.shell.server import make_server
from app.system.runtime_state import atomic

def run(root):
    f=AgentAutoFixture(root);a=f.advisory;a.source='USER' # Isolated Fake only, matching persisted production completion contract.
    f.now=datetime.fromisoformat('2026-09-18T09:20:00+08:00')
    # The listener has not discovered a session yet (premarket source outage).
    with a.runtime.connect() as db:
        db.execute("DELETE FROM native_control WHERE kind='AUTO_POLICY_BOUNDARY'")
        db.execute("UPDATE advisory_settings SET updated_at='2026-09-18T01:19:00+00:00'")
    sender=FakeSender();notice=Notifications(ScopedStore(root/'notify',boundary=root),TelegramConfig(True,'123:'+('x'*30),chat_id='100001',allowed_chat_id='100001'),sender,a,clock=lambda:f.now)
    a.success_observer=notice.completed;notice.start()
    server=make_server(f.app,0);f.app.runtime.server=server
    server.control_token='isolated-test-token';server.instance_id='isolated-test-instance'
    f.app.runtime.start();connected=f.bridge.connected;f.bridge.connected=lambda:False
    stop=threading.Event()
    def frames():
        last=None
        while not stop.wait(.05):
            try:command=json.loads((root/'clock.json').read_text())
            except (OSError,ValueError):command={}
            phase=command.get('phase')
            if phase!=last:
                if phase=='open':
                    f.bridge.connected=connected;f.now=datetime.fromisoformat('2026-09-18T09:35:40+08:00');f.advance_native()
                if phase=='clear':f.bridge.connected=connected
                last=phase
            if phase=='open':f.now+=timedelta(seconds=.5)
            atomic(root/'evidence.json',{'calls':len(f.provider.calls),'messages':len(sender.sent),'loop':f.app.live_loop.runtime_status(),
                'opinions':len(a.history('bj920161')),'account_bound':f.p.binding().get('account_id'),
                'cursor':a.runtime.cursor(f.bridge.advisory_facts('bj920161')['session']['tracking_session_id'])})
    worker=threading.Thread(target=frames,daemon=True);worker.start()
    atomic(root/'ready.json',{'url':f'http://127.0.0.1:{server.server_port}'})
    try:server.serve_forever()
    finally:
        stop.set();worker.join(3);notice.close();f.app.runtime.close();server.server_close();f.close()
if __name__=='__main__':run(Path(sys.argv[1]).resolve())
