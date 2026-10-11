"""Offline allowlisted build. Inputs are reviewed locks, never a running installation."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,re,shutil,stat,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(p):return json.loads(Path(p).read_text('utf-8-sig'))
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def require(v,s):
 if not v:raise RuntimeError(s)
def safe(p,root=ROOT):
 p=Path(p).absolute();require(p.is_relative_to(root),'PATH_OUTSIDE_WORKSPACE')
 for a in (p,*p.parents):
  if a.exists():require(not(a.lstat().st_file_attributes&1024),'REPARSE_POINT')
 if p.is_file():require(p.stat().st_nlink==1,'HARDLINK')
 return p
def inventory(root):
 result={}
 for folder,dirs,names in os.walk(root,followlinks=False):
  for n in dirs+names:safe(Path(folder)/n)
  for n in names:
   p=Path(folder)/n;result[p.relative_to(root).as_posix()]=sha(p)
 return dict(sorted(result.items()))
def source_files():
 result=[]
 for folder in ('app','adapters','bridges','contracts','engines','shared','config'):
  for p in (ROOT/folder).rglob('*'):
   safe(p)
   if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'):result.append(p.relative_to(ROOT).as_posix())
 result+=['trading_lab.py','market_data_agent.py','requirements.txt','requirements-lock.txt','README.md','.env.example','.env.telegram.example','docs/ARCHITECTURE.md','docs/DATA_OWNERSHIP.md','docs/CONTRACTS.md','docs/frozen_baselines.json','docs/FROZEN_BASELINES.md','tools/runtime_control.py']
 result += [r['path'] for r in load(ROOT/'docs/frozen_baselines.json')['files']]
 return sorted(set(result))
def scan(paths):
 hits=[]
 patterns={'api_key':r'\bsk-[A-Za-z0-9_-]{20,}','telegram_token':r'\b\d{7,12}:[A-Za-z0-9_-]{25,}','private_key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----','credential_url':r'https?://[^\s/:]+:[^\s/@]+@','account_id':r'\bAC-[a-f0-9]{32}\b'}
 for rel in paths:
  require((not Path(rel).name.startswith('.env') or Path(rel).name.endswith('.example')) and Path(rel).suffix.lower() not in ('.db','.sqlite','.sqlite3','.wal','.shm','.log'),'PRIVATE_FILE_IN_ALLOWLIST:'+rel)
  raw=(ROOT/rel).read_text('utf-8-sig',errors='replace')
  for kind,pattern in patterns.items():
   if re.search(pattern,raw):hits.append({'path':rel,'kind':kind})
 require(not hits,'SECRET_OR_ACCOUNT_PATTERN:'+json.dumps(hits))
 for template in ('.env.example','.env.telegram.example'):
  for line in (ROOT/template).read_text('utf-8').splitlines():
   if not line.strip() or line.startswith('#'):continue
   key,sep,value=line.partition('=');require(sep and (not value or (key=='TELEGRAM_NOTIFICATIONS_ENABLED' and value=='false')),'NONEMPTY_ENV_TEMPLATE')
 # The Adapter must not regain any literal personal recipient in a default or check.
 import ast
 tree=ast.parse((ROOT/'adapters/telegram.py').read_text('utf-8'))
 require(not any(isinstance(n,ast.Constant) and isinstance(n.value,str) and re.fullmatch(r'[0-9]{6,}',n.value) for n in ast.walk(tree)),'LITERAL_TELEGRAM_RECIPIENT')
 return {'credential_patterns':'PASS','files_scanned':len(paths),'scope':'Allowlisted first-party inputs and both empty dotenv templates. Runtime verified against the fixed lock. Full-payload privacy scan remains a release review step.','telegram_authorization':'LOCAL_PRIVATE_FILE_ONLY; no literal recipient','public_distribution':'PENDING_RELEASE_REVIEW'}

def build(output,artifact,lockpath,configpath):
 output=safe(output);require(output.is_relative_to(ROOT/'.dev') and output!=ROOT/'.dev','OUTPUT_MUST_BE_NEW_DEV_CHILD');require(not output.exists(),'OUTPUT_EXISTS_REFUSED')
 lockpath=safe(lockpath);configpath=safe(configpath);artifact=safe(artifact)
 lock=load(lockpath);cfg=load(configpath);rt=load(ROOT/'dev/runtime-lock.json')
 require(cfg['schema']==1 and cfg['profile']=='TEST','INVALID_BUILD_CONFIG')
 require(sha(configpath)==lock['build_config_sha256'],'BUILD_CONFIG_CHANGED')
 require(sha(ROOT/'dev/runtime-lock.json')==lock['runtime_lock_sha256'],'RUNTIME_LOCK_CHANGED')
 require(set(source_files())==set(lock['business']),'BUSINESS_ALLOWLIST_CHANGED')
 for rel,digest in {**lock['business'],**lock['build_inputs']}.items():
  p=safe(ROOT/rel);require(p.is_file() and sha(p)==digest,'SOURCE_CHANGED:'+rel)
 require(sha(ROOT/'requirements-lock.txt')==rt['requirements_sha256'],'REQUIREMENTS_LOCK_CHANGED')
 require(artifact.stat().st_size==rt['artifact']['bytes'] and sha(artifact)==rt['artifact']['sha256'],'RUNTIME_ZIP_SHA_MISMATCH')
 require(Path(sys.executable).resolve()==ROOT/'.dev/runtime/python/python.exe' and sys.version_info[:3]==(3,12,14) and sys.maxsize>2**32,'FIXED_INTERPRETER_REQUIRED')
 safety=scan(list(lock['business'])+list(lock['build_inputs']))
 expected={r['path']:r for r in rt['files']}
 with zipfile.ZipFile(artifact) as z:
  names=z.namelist();require(len(names)==len(set(n.lower() for n in names)) and set(names)==set(expected),'ZIP_CONTENT_SET_MISMATCH')
  for info in z.infolist():
   n=info.filename;parts=PurePosixPath(n).parts
   require(not n.startswith('/') and not re.search(r'[\\:]|(^|/)\.\.?(/|$)|[. ]($|/)',n) and parts[0] in ('python','node'),'UNSAFE_ZIP_PATH')
   require(stat.S_IFMT(info.external_attr>>16)!=stat.S_IFLNK and info.file_size==expected[n]['bytes'],'ZIP_TYPE_SIZE_MISMATCH')
   require(hashlib.sha256(z.read(info)).hexdigest()==expected[n]['sha256'],'ZIP_ENTRY_SHA_MISMATCH:'+n)
  output.mkdir(parents=True);(output/'BUILD_INCOMPLETE').write_text('Build has not passed final validation.','utf-8')
  for rel,digest in lock['business'].items():
   dst=output/'TradingLab'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst);require(sha(dst)==digest,'COPY_CHANGED:'+rel)
  for rel in cfg['deployment_files']:
   dst=output/Path(rel).name;shutil.copyfile(ROOT/rel,dst)
  for info in z.infolist():
   dst=output/'runtime'/info.filename;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(z.read(info))
 save(output/'runtime/runtime-lock.json',rt)
 save(output/'runtime/source-original.json',lock['business'])
 save(output/'runtime/build-inputs.json',{'schema':1,'source_lock_sha256':sha(lockpath),'build_config_sha256':sha(configpath),'runtime_lock_sha256':sha(ROOT/'dev/runtime-lock.json'),'runtime_zip_sha256':rt['artifact']['sha256'],'source':lock['business'],'build_inputs':lock['build_inputs']})
 save(output/'runtime/security-scan.json',safety)
 save(output/'runtime/provenance.json',{'version':cfg['version'],'python':rt['python'],'node':rt['node'],'dependencies':rt['dependencies'],'licenses':rt['licenses'],'privacy':'PENDING_RELEASE_REVIEW','source_changes_during_build':[],'runtime_zip_sha256':rt['artifact']['sha256']})
 save(output/'portable.json',{'schema':1,'profile':'TEST','web_port':cfg['web_port'],'agent_port':cfg['agent_port'],'open_browser':False})
 # Deterministic launchers; standalone generation has no fixed output-directory side effects.
 sys.path.insert(0,str(ROOT/'portable-work'))
 sys.path.insert(0,str(ROOT/'portable-work'))
 sys.path.insert(0,str(ROOT/'portable-work'))
 sys.path.insert(0,str(ROOT/'portable-work'))
 import install_launchers
 install_launchers.install(output)
 manifest=inventory(output);manifest.pop('BUILD_INCOMPLETE')
 save(output/'runtime/files.json',manifest)
 (output/'SHA256SUMS').write_text(''.join(h+'  '+p+'\n' for p,h in sorted({**manifest,'runtime/files.json':sha(output/'runtime/files.json')}.items())),encoding='utf-8')
 require(all(sha(output/p)==h for p,h in manifest.items()),'FINAL_HASH_MISMATCH')
 require({p:sha(output/'TradingLab'/p) for p in lock['business']}==lock['business'],'BUSINESS_CONTENT_CHANGED')
 probe="import sys,json,platform,importlib.metadata as m;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import portable_control,portable_test_control,jiter,pydantic_core,rpds,ssl,sqlite3;print(json.dumps({'python':platform.python_version(),'packages':{d.metadata['Name']:d.version for d in m.distributions()},'base':str(Path(sys.base_prefix).resolve())}))"
 env={k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONPATH','PYTHONHOME','NODE_OPTIONS')};env['PYTHONDONTWRITEBYTECODE']='1'
 result=json.loads(subprocess.check_output([str(output/'runtime/python/python.exe'),'-I','-B','-X','utf8','-c',probe,str(output)],env=env,cwd=output,text=True))
 normalize=lambda s:re.sub('[-_.]+','-',s).lower()
 require(result['python']==rt['python'] and Path(result['base'])==(output/'runtime/python').resolve(),'OUTPUT_PYTHON_VERSION_PATH')
 require({normalize(k):v for k,v in result['packages'].items()}=={normalize(k):v for k,v in rt['dependencies'].items()},'OUTPUT_DEPENDENCIES')
 require(subprocess.check_output([str(output/'runtime/node/node.exe'),'--version'],env=env,cwd=output,text=True).strip()=='v'+rt['node'],'OUTPUT_NODE_VERSION')
 (output/'BUILD_INCOMPLETE').unlink()
 final=inventory(output)
 print(json.dumps({'status':'PASS','output':str(output),'files':len(final),'bytes':sum((output/p).stat().st_size for p in final),'business_files':len(lock['business']),'runtime_files':len(expected),'manifest_sha256':sha(output/'runtime/files.json'),'file_set_sha256':hashlib.sha256(json.dumps(final,sort_keys=True).encode()).hexdigest(),'security':safety},ensure_ascii=False))
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--artifact',required=True,type=Path);p.add_argument('--source-lock',type=Path,default=ROOT/'portable-work/source-lock.json');p.add_argument('--config',type=Path,default=ROOT/'portable-work/build-config.json');a=p.parse_args()
 try:build(a.output,a.artifact,a.source_lock,a.config)
 except Exception as e:print('BUILD_BLOCKED: '+str(e),file=sys.stderr);return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
