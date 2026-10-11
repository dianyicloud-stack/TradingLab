"""Execute the actual candidate TEST guard with a harmless replacement entry callback."""
from pathlib import Path
import sys,json,os,runpy,sqlite3,socket,subprocess
from unittest.mock import patch
package=Path(sys.argv[1]).resolve();sys.path.insert(0,str(package));import portable_test_control as control
assert not any(k in control.environment() for k in ('DEEPSEEK_API_KEY','TELEGRAM_BOT_TOKEN','TELEGRAM_NOTIFICATIONS_ENABLED','PYTHONPATH','PYTHONHOME','NODE_OPTIONS'))
blocked=[]
def probe(path,run_name):
 assert Path(path)==package/'TradingLab/trading_lab.py'
 for name,operation in [
  ('external_network',lambda:socket.create_connection(('example.com',443),timeout=1)),
  ('outside_sandbox_write',lambda:(package/'must-not-exist.txt').write_text('denied')),
  ('outside_sandbox_database',lambda:sqlite3.connect(package/'must-not-exist.db')),
  ('unapproved_child_process',lambda:subprocess.run([sys.executable,'-c','print(1)']))]:
  try:operation()
  except PermissionError:blocked.append(name)
  else:raise AssertionError('Guard failed: '+name)
child=package/'portable_test_child.py';code=compile(child.read_text('utf-8'),str(child),'exec');sys.argv=[str(child),'trading_lab.py']
with patch.object(runpy,'run_path',probe):exec(code,{'__file__':str(child),'__name__':'__main__'})
assert len(blocked)==4
print(json.dumps({'status':'PASS','real_candidate_guard':True,'blocked':blocked,'credentials_and_external_python_node_environment':'not propagated'}))
