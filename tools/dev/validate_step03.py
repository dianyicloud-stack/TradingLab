"""Reproducible local STEP03 checks; all generated work stays in .dev/validation.

Does not start, stop, inspect databases or change settings of other projects.
"""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, time, zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/dev'))
import control as c
OUT=ROOT/'.dev/validation';OUT.mkdir(exist_ok=True)
STAGE=(OUT/os.environ.get('TL_DEV_VALIDATION_NAME','中文 空格 开发副本')).resolve()
if STAGE==OUT or not STAGE.is_relative_to(OUT):raise RuntimeError('Validation name must remain below .dev/validation')
def prepare():
    if STAGE.exists():raise RuntimeError('Validation directory already exists; keep evidence and choose a new name')
    shutil.copytree(ROOT,STAGE,ignore=shutil.ignore_patterns('.dev','.venv','__pycache__','.git','.env'))
    print(STAGE)
def invoke(name,args,expect=0,env=None,cwd=None,timeout=300):
    started=time.time();log=OUT/(name+'.log')
    if log.exists():
        history=OUT/'history';history.mkdir(exist_ok=True)
        shutil.copy2(log,history/(str(time.time_ns())+'-'+log.name))
    with log.open('wb') as output:
        result=subprocess.run(args,env=env or c.environment(),cwd=cwd or OUT,stdout=output,stderr=subprocess.STDOUT,timeout=timeout)
    row={'name':name,'exit_code':result.returncode,'expected':expect,'status':'PASS' if result.returncode==expect else 'FAIL','seconds':round(time.time()-started,2),'log':log.name}
    with (OUT/'results.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps(row,ensure_ascii=False),flush=True)
    return row
def entry(name,action,root=STAGE,extra=None,expect=0,env=None):
    ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Invoke the actual .cmd, from a directory other than the project root.
    command="& '"+str(root/(action+'-Dev.cmd')).replace("'","''")+"'"
    for a in extra or []:command+=" '"+str(a).replace("'","''")+"'"
    return invoke(name,[str(ps),'-NoProfile','-Command',command+'; exit $LASTEXITCODE'],expect,env)
def entries():
    lock=json.loads((ROOT/'dev/runtime-lock.json').read_text('utf-8'))
    artifact=ROOT/'.dev/artifacts'/lock['artifact']['filename']
    entry('missing-artifact','Setup',extra=['-Artifact',OUT/'absent.zip'],expect=1)
    bad=OUT/'corrupt.zip';bad.write_bytes(b'not a runtime')
    entry('corrupt-artifact','Setup',extra=['-Artifact',bad],expect=1)
    env=c.environment();env.update(PATH=os.environ['SystemRoot']+'\\System32',PYTHONHOME=str(OUT/'nonexistent-python'),PYTHONPATH=str(OUT/'untrusted'))
    entry('chinese-setup-poisoned-system','Setup',extra=['-Artifact',artifact],env=env)
    before=c.sha(STAGE/'.dev/venv-seal.json')
    entry('chinese-setup-repeat','Setup',extra=['-Artifact',artifact],env=env)
    assert before==c.sha(STAGE/'.dev/venv-seal.json')
    entry('chinese-check','Check',env=env)
    try:entry('chinese-start','Start',env=env)
    finally:entry('chinese-stop','Stop',env=env)
    entry('chinese-stop-repeat','Stop',env=env)
    entry('chinese-check-after-stop','Check',env=env)
def suite():
    env=c.environment();env['TRADING_LAB_NODE']=str(STAGE/'.dev/runtime/node/node.exe')
    env['TEMP']=env['TMP']=str(STAGE/'.dev/temp')
    py=STAGE/'.venv/Scripts/python.exe'
    invoke('unittest',[str(py),'-B','-X','utf8','-m','unittest','discover','-s','tests','-v'],cwd=STAGE,env=env,timeout=900)
    invoke('baselines',[str(py),'-B','-X','utf8','trading_lab.py','--verify-baselines'],cwd=STAGE,env=env)
def negative():
    # Invalid archives have matching artifact hashes so tests reach ZIP checks.
    for label,name,mode in [('traversal','../escape.txt',0o100644),('absolute','C:/escape.txt',0o100644),('symlink','python/link',0o120777),('unexpected','python/extra',0o100644)]:
        project=OUT/('zip-'+label);(project/'tools/dev').mkdir(parents=True,exist_ok=True);(project/'dev').mkdir(exist_ok=True)
        shutil.copy2(ROOT/'tools/dev/bootstrap.ps1',project/'tools/dev/bootstrap.ps1');shutil.copy2(ROOT/'Setup-Dev.cmd',project/'Setup-Dev.cmd')
        artifact=project/'bad.zip'
        with zipfile.ZipFile(artifact,'w') as archive:
            info=zipfile.ZipInfo(name);info.external_attr=mode<<16;archive.writestr(info,b'x')
        lock={'python':'3.12.14','node':'24.19.0','artifact':{'sha256':c.sha(artifact)},'files':[{'path':name if label!='unexpected' else 'python/expected','bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}]}
        (project/'dev/runtime-lock.json').write_text(json.dumps(lock),encoding='utf-8')
        entry('zip-'+label,'Setup',root=project,extra=['-Artifact',artifact],expect=1)
    assert not (OUT/'escape.txt').exists()
    source=STAGE/'trading_lab.py';original=source.read_bytes()
    try:
        source.write_text("raise RuntimeError('STEP03_INJECTED_START_FAILURE')\n",encoding='utf-8')
        entry('startup-failure-rollback','Start',expect=1)
    finally:source.write_bytes(original)
    entry('after-rollback','Check')
    injected=STAGE/'.venv/Lib/site-packages/step03-unexpected.pth'
    try:
        injected.write_text("import sys; raise RuntimeError('MUST_NOT_EXECUTE')\n",encoding='utf-8')
        entry('venv-unlisted-file','Check',expect=1)
    finally:injected.unlink()
    runtime=STAGE/'.dev/runtime/node/LICENSE.txt';original=runtime.read_bytes()
    try:
        runtime.write_bytes(original+b'corrupt')
        entry('runtime-corruption','Check',expect=1)
    finally:runtime.write_bytes(original)
    with __import__('socket').socket() as listener:
        listener.bind(('127.0.0.1',18765));listener.listen()
        entry('port-occupied','Start',expect=1)
    entry('after-negative-check','Check')
def final_checks():
    for name in ('control.py','child.py','bootstrap.ps1'):shutil.copy2(ROOT/'tools/dev'/name,STAGE/'tools/dev'/name)
    source=STAGE/'trading_lab.py';original=source.read_bytes()
    try:
        source.write_text("raise RuntimeError('STEP03_INJECTED_START_FAILURE')\n",encoding='utf-8')
        entry('final-startup-failure-rollback','Start',expect=1)
        text=(OUT/'final-startup-failure-rollback.log').read_text('utf-8')
        assert '-web.log' in text and 'DEV Web / Agent' in text,'Failure did not reach intended Web startup phase'
    finally:source.write_bytes(original)
    entry('final-check-after-rollback','Check')
    try:entry('final-chinese-start','Start')
    finally:entry('final-chinese-stop','Stop')
    entry('final-chinese-stop-repeat','Stop')
    entry('final-chinese-check','Check')
    # Test the launcher's actual audit boundary using a temporary DEV-only entry.
    probe="""import socket,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
checks=[]
for name,operation in [
 ('external_network',lambda:socket.create_connection(('example.com',443),timeout=1)),
 ('outside_write',lambda:(root/'should-not-exist.txt').write_text('denied')),
 ('real_ai_child',lambda:subprocess.run([sys.executable,'-c','print(1)']))]:
 try:operation()
 except PermissionError:checks.append(name)
 else:raise AssertionError(name+' not blocked')
assert len(checks)==3
print('PASS: '+','.join(checks))
"""
    try:
        source.write_text(probe,encoding='utf-8')
        env=c.environment();env['TRADING_LAB_NODE']=str(STAGE/'.dev/runtime/node/node.exe')
        invoke('final-boundary-guard',[str(STAGE/'.venv/Scripts/python.exe'),'-I','-B',str(STAGE/'tools/dev/child.py'),'trading_lab.py'],env=env)
        assert not (STAGE/'should-not-exist.txt').exists()
    finally:source.write_bytes(original)
if __name__=='__main__':{'prepare':prepare,'entries':entries,'suite':suite,'negative':negative,'final':final_checks}[sys.argv[1]]()
