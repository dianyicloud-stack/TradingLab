"""Run ONLY against the disposable portable validation package. No production commands."""
from pathlib import Path
import contextlib,hashlib,json,os,shutil,socket,sqlite3,subprocess,sys,tempfile,time,urllib.request
WORK=Path(__file__).resolve().parent
PKG=WORK/'validation/便携 测试 A'
OUT=WORK/'deployment-results.json'
RESULTS={}
def record(name,**data):
    RESULTS[name]={'status':'PASS',**data};OUT.write_text(json.dumps(RESULTS,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name+': PASS',flush=True)
def control(root,action,expect=0,extra=()):
    env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    env['PYTHONHOME']='Z:/does-not-exist';env['PYTHONPATH']='Z:/does-not-exist'
    p=subprocess.run([str(root/'runtime/python/python.exe'),'-I','-B',str(root/'portable_control.py'),action,*extra],
        cwd=Path(os.environ['SystemRoot']),env=env,capture_output=True,text=True,encoding='utf-8',timeout=100)
    assert p.returncode==expect,(action,p.returncode,p.stdout,p.stderr)
    return p.stdout
def get(root,path):
    port=json.loads((root/'portable.json').read_text())['web_port']
    with urllib.request.urlopen(f'http://127.0.0.1:{port}'+path,timeout=15) as r:return json.load(r)
def alive(root):
    # Read only owned descriptors via original Owner process identity function.
    sys.path.insert(0,str(root/'TradingLab'))
    from adapters.runtime_platform import alive as is_alive
    result=[]
    for rel in ('TradingLab/data/runtime/supervisor.json','TradingLab/data/runtime/web-instance.json','MarketDataAgent/connection.json'):
        p=root/rel
        if p.exists():
            r=json.loads(p.read_text());
            if is_alive(r):result.append(r['pid'])
    return result
def main():
    root=PKG;assert root.is_relative_to(WORK) and (root/'portable.json').exists()
    health=get(root,'/healthz');before=health['instance_id']
    control(root,'start',extra=('--no-browser',));assert get(root,'/healthz')['instance_id']==before
    record('duplicate_start_reuses_instance',instance_id=before)
    source=get(root,'/api/system/market-source');assert Path(source['source_root'])==root/'MarketDataAgent'
    record('source_root_is_local_to_bundle',source=source['active_market_source'],owner=source['source_owner'])
    state=json.loads((WORK/'persistence-test.json').read_text());account=state['account_id']
    a=get(root,'/api/accounts/'+account);assert a['cash']==10000 and not a['positions']
    record('isolated_account_created_via_original_api',cash=a['cash'],account_id=account)
    control(root,'stop');assert not alive(root)
    record('graceful_stop_no_owned_processes')
    control(root,'start',extra=('--no-browser',));a2=get(root,'/api/accounts/'+account)
    assert a['cash']==a2['cash'] and a['account_id']==a2['account_id'] and a['executions']==a2['executions']
    record('account_persistence_restart',cash=a2['cash'],positions=a2['positions'],executions=a2['executions'])
    control(root,'stop');assert not alive(root)
    renamed=WORK/'validation/重命名后的 TradingLab'
    assert not renamed.exists();root.rename(renamed);root=renamed
    try:
        control(root,'start',extra=('--no-browser',));assert get(root,'/api/accounts/'+account)['cash']==10000
        record('renamed_directory_with_spaces_and_chinese',path=str(root))
    finally:control(root,'stop')
    assert not alive(root)
    # Actual C: copy, not a SUBST alias. Isolated temporary directory outside other projects.
    drive=Path(tempfile.mkdtemp(prefix='TradingLab-portable-C-'))/'Portable'
    assert drive.drive!=root.drive and not drive.exists()
    shutil.copytree(root,drive)
    try:
        control(drive,'start',extra=('--no-browser',));a3=get(drive,'/api/accounts/'+account)
        assert a3['cash']==10000 and a3['account_id']==account
        record('actual_different_drive_complete_copy',from_drive=root.drive,to_drive=drive.drive,account_persisted=True)
    finally:control(drive,'stop')
    assert not alive(drive)
    record('no_global_python_in_process_path',python=str(drive/'runtime/python/python.exe'),poisoned_python_env_ignored=True,
        clean_machine='NOT_TESTED')
    # Failures never affect other processes/data. Mutations are confined to this disposable copy.
    config=json.loads((drive/'portable.json').read_text());config['web_port']=8765
    (drive/'portable.json').write_text(json.dumps(config))
    output=control(drive,'start',expect=1);assert '被其他程序占用' in output
    record('foreign_port_conflict_refused')
    config['web_port']=json.loads((root/'portable.json').read_text())['web_port'];(drive/'portable.json').write_text(json.dumps(config))
    dep=drive/'runtime/python/Lib/site-packages/openai';hidden=dep.with_name('_unavailable_openai');dep.rename(hidden)
    try:assert 'ModuleNotFoundError' in control(drive,'check',expect=1)
    finally:hidden.rename(dep)
    record('missing_dependency_diagnosed')
    database=drive/'TradingLab/data/system/ai-configuration.db';saved=database.read_bytes();database.write_bytes(b'not a sqlite database')
    try:assert '数据库无法读取' in control(drive,'check',expect=1)
    finally:database.write_bytes(saved)
    record('invalid_database_refused_without_initialization')
    entry=drive/'TradingLab/trading_lab.py';saved=entry.read_bytes();entry.write_text('raise SystemExit(7)\n',encoding='utf-8')
    try:
        assert '正常回退' in control(drive,'start',expect=1)
        assert not alive(drive)
    finally:entry.write_bytes(saved)
    record('new_launch_failure_graceful_rollback')
    control(drive,'start',extra=('--no-browser',));assert get(drive,'/api/accounts/'+account)['cash']==10000
    control(drive,'stop');assert not alive(drive)
    record('rollback_preserves_existing_database')
    # Verify every delete target is one of our freshly created temp roots.
    assert drive.parent.name.startswith('TradingLab-portable-C-') and drive.parent.parent==Path(tempfile.gettempdir()).resolve()
    shutil.rmtree(drive.parent)
    record('temporary_other_drive_copy_removed')
    print('Deployment verification complete; source validation data retained for migration test.',flush=True)
if __name__=='__main__':main()
