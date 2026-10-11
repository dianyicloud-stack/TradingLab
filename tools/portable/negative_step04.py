"""Negative acceptance cases against owned STEP04 candidate data only."""
from pathlib import Path
import json,os,socket,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools/portable'))
import validate_step04 as v
A=v.A;OUT=v.OUT

def main():
 with socket.socket() as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);s.bind(('127.0.0.1',28765));s.listen()
  v.entry('negative-port-conflict',A,'Start',expected=1)
 missing=A/'runtime/python/Lib/site-packages/yaml/__init__.py';data=missing.read_bytes()
 try:
  missing.unlink();v.entry('negative-missing-dependency',A,'Check',expected=1)
 finally:missing.write_bytes(data)
 db=next((A/'TradingLab/sandbox/data/account/unified').glob('AC-*/account.db'));original=db.read_bytes()
 try:
  db.write_bytes(b'STEP04 corrupt synthetic database');v.entry('negative-corrupt-database',A,'Start',expected=1)
 finally:db.write_bytes(original)
 incomplete=A/'BUILD_INCOMPLETE'
 try:
  incomplete.write_text('Synthetic incomplete build');v.entry('negative-incomplete-build',A,'Start',expected=1)
 finally:incomplete.unlink()
 private=A/'TradingLab/.env'
 try:
  private.write_text('DEEPSEEK_API_KEY=SYNTHETIC_TEST_VALUE\n');v.entry('negative-private-env',A,'Start',expected=1)
 finally:private.unlink()
 v.invoke('negative-startup-rollback',[A/'runtime/python/python.exe','-I','-B','-X','utf8',ROOT/'portable-work/tests/step04_scenarios.py',A,ROOT,'rollback'])
 v.entry('negative-after-check',A,'Check')
 # The actual build entry must refuse existing data and damaged Runtime input.
 sentinel=OUT/'occupied-output';sentinel.mkdir();(sentinel/'user-content.txt').write_text('KEEP')
 v.entry('build-existing-output-refused',ROOT,'Build-Portable',expected=1,extra=['-Output',sentinel])
 assert (sentinel/'user-content.txt').read_text()=='KEEP'
 bad=OUT/'damaged-runtime.zip';bad.write_bytes(b'not a ZIP')
 v.entry('build-damaged-runtime-refused',ROOT,'Build-Portable',expected=1,extra=['-Output',OUT/'must-not-build','-Artifact',bad]);assert not (OUT/'must-not-build').exists()
 lock=json.loads((ROOT/'portable-work/source-lock.json').read_text('utf-8'));lock['business']['app/shell/server.py']='0'*64
 altered=OUT/'wrong-source-lock.json';altered.write_text(json.dumps(lock),encoding='utf-8')
 rt=json.loads((ROOT/'dev/runtime-lock.json').read_text('utf-8'))
 v.invoke('build-source-drift-refused',[ROOT/'.dev/runtime/python/python.exe','-I','-B','-X','utf8',ROOT/'portable-work/build_portable.py','--output',OUT/'must-not-build-source','--artifact',ROOT/'.dev/artifacts'/rt['artifact']['filename'],'--source-lock',altered],expected=1)
 assert not (OUT/'must-not-build-source').exists()
 v.save('negative-summary.json',{'status':'PASS','cases':['port conflict','missing dependency','corrupt owned synthetic database','incomplete build','private env rejected','Web launch failure rolls back already-started Agent','existing output refused without changes','damaged Runtime ZIP refused','source hash drift refused'],'business_files_modified_for_tests':False,'integrity_checks_disabled':False})
if __name__=='__main__':main()
