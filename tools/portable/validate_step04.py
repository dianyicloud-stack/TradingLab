"""STEP04 repeatable local validation; writes only .dev/step04 and candidate sandbox."""
from pathlib import Path
import hashlib,json,os,shutil,socket,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'.dev/step04';A=OUT/'approved-a/TradingLabPortable';B=OUT/'中文 空格 验收 B/TradingLabPortable'
sys.path.insert(0,str(ROOT/'tools/dev'));import control as dev
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def env():
 e=dev.environment();e.update(TRADINGLAB_NONINTERACTIVE='1',TEMP=str(OUT/'temp'),TMP=str(OUT/'temp'));(OUT/'temp').mkdir(exist_ok=True);return e
def invoke(name,args,expected=0,cwd=OUT,custom=None,timeout=600):
 path=OUT/(name+'.txt')
 if path.exists():raise RuntimeError('Keep existing evidence: '+name)
 started=time.monotonic()
 with path.open('wb') as log:r=subprocess.run(list(map(str,args)),cwd=cwd,env=custom or env(),stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 row={'name':name,'exit_code':r.returncode,'expected':expected,'status':'PASS' if r.returncode==expected else 'FAIL','seconds':round(time.monotonic()-started,3),'cwd':str(cwd),'command':list(map(str,args))}
 with (OUT/'runs.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 print(json.dumps(row,ensure_ascii=False),flush=True)
 assert r.returncode==expected,path.read_text('utf-8',errors='replace')
 return row
def entry(name,root,action,expected=0,extra=(),custom=None):
 words=[root/(action+'.cmd'),*extra];command='& '+' '.join("'"+str(v).replace("'","''")+"'" for v in words)+'; exit $LASTEXITCODE'
 return invoke(name,[PS,'-NoProfile','-Command',command],expected,custom=custom)
def request(record,path,payload=None):
 req=urllib.request.Request(record['url']+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Authorization':'Bearer '+record.get('token',''),'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as r:
  body=r.read();return r.status,json.loads(body) if r.headers.get_content_type()=='application/json' else body.decode('utf-8')
def compare():
 left=dev.seal(A);right=dev.seal(B)
 assert left==right
 save('approved-build-comparison.json',{'status':'PASS','a':str(A),'b':str(B),'files':len(left),'bytes':sum((A/p).stat().st_size for p in left),'differences':[],'files_sha256':left,'outer_zip_byte_equality':'NOT_APPLICABLE: no Portable ZIP produced','runtime_zip_identical':True})
 print('Initial candidate payloads identical:',len(left),flush=True)
def runtime(root,label):
 poison=env();poison.update(PATH=os.environ['SystemRoot']+'\\System32',PYTHONHOME=str(OUT/'untrusted'),PYTHONPATH=str(OUT/'untrusted'),TRADING_LAB_SOURCE='USER',DEEPSEEK_API_KEY='SYNTHETIC_MUST_NOT_PROPAGATE',TELEGRAM_NOTIFICATIONS_ENABLED='true',NODE_OPTIONS='--invalid-option-for-isolation-check')
 entry(label+'-check',root,'Check',custom=poison)
 try:
  entry(label+'-start',root,'Start',custom=poison)
  state=json.loads((root/'TradingLab/sandbox/instances.json').read_text('utf-8'));web=state['web'];agent=state['agent']
  evidence={'pages':{},'health':request(web,'/healthz')[1],'agent':request(agent,'/v1/health')[1]}
  for path in ('/live','/data-observation','/account','/system'):
   status,html=request(web,path);assert status==200 and '<html' in html.lower();evidence['pages'][path]={'status':status,'bytes':len(html.encode())}
  evidence['system']=request(web,'/api/system/summary')[1]
  evidence['agent_state']=request(agent,'/v1/state')[1]
  status,catalog=request(web,'/api/accounts');assert status==200
  payload={'name':'STEP04 合成账户 '+label,'idempotency_key':'step04-'+label,'initial_capital':100000,'policy':catalog['default_policy']}
  status,account=request(web,'/api/accounts',payload);assert status==201;assert account['namespace'].startswith('TEST')
  evidence['account_before']={'account_id':account['account_id'],'initial_capital':account['initial_capital'],'namespace':account['namespace']}
  entry(label+'-repeat-start',root,'Start',expected=1)
  state2=json.loads((root/'TradingLab/sandbox/instances.json').read_text('utf-8'));assert state2==state
  entry(label+'-stop',root,'Stop')
  entry(label+'-restart',root,'Start')
  state=json.loads((root/'TradingLab/sandbox/instances.json').read_text('utf-8'));status,persisted=request(state['web'],'/api/accounts/'+account['account_id']);assert status==200
  assert persisted['account_id']==account['account_id'] and persisted['initial_capital']==account['initial_capital'] and persisted['namespace']==account['namespace']
  evidence['persistence']='PASS';evidence['runtime']=json.loads((root/'TradingLab/sandbox/check-result.json').read_text('utf-8'))
  save(label+'-runtime.json',evidence)
 finally:entry(label+'-final-stop',root,'Stop')
 entry(label+'-stop-again',root,'Stop')
 entry(label+'-after-check',root,'Check')
def suite():
 project=OUT/'regression-project';shutil.copytree(OUT/'before-source',project)
 e=env();e['TRADING_LAB_NODE']=str(A/'runtime/node/node.exe')
 invoke('full-regression',[ROOT/'.venv/Scripts/python.exe','-B','-X','utf8','-m','unittest','discover','-s','tests','-v'],cwd=project,custom=e,timeout=900)
 invoke('frozen-baselines',[ROOT/'.venv/Scripts/python.exe','-B','-X','utf8','trading_lab.py','--verify-baselines'],cwd=project,custom=e)
def deployment():
 work=A.parent;(work/'tests').mkdir(exist_ok=True)
 shutil.copyfile(ROOT/'portable-work/tests/test_portable.py',work/'tests/test_portable.py');shutil.copyfile(ROOT/'portable-work/source-before.json',work/'source-before.json')
 invoke('approved-deployment-14',[A/'runtime/python/python.exe','-I','-B','-X','utf8',work/'tests/test_portable.py','-v'])
if __name__=='__main__':{'compare':compare,'a':lambda:runtime(A,'a3'),'b':lambda:runtime(B,'b3'),'suite':suite,'deployment':deployment}[sys.argv[1]]()
