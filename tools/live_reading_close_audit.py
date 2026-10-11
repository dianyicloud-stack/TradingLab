from pathlib import Path
import json,hashlib,sqlite3,urllib.request
from datetime import datetime,timezone
root=Path.cwd();out=root/'artifacts/live_reading_closure';before=json.loads((out/'before.json').read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(p):return {x.relative_to(p).as_posix():digest(x) for x in p.rglob('*') if x.is_file()}
def changes(a,b):return sorted(set(a)^set(b)|{k for k in a.keys()&b.keys() if a[k]!=b[k]})
after={}
for category in ('legacy','data'):
 after[category]={category+'/'+k:v for k,v in inventory(root/category).items()}
workspace=Path(before['workspace_path']);workspace_after=inventory(workspace)
result={'created_at':datetime.now(timezone.utc).isoformat(),'legacy_count':len(after['legacy']),
 'legacy_changes':changes(before['legacy'],after['legacy']),'workspace_changes':changes(before['workspace'],workspace_after),'data_changes':changes(before['data'],after['data']),'sqlite':{},'api':{}}
def tables(path):
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  result={}
  for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
   rows=db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall()
   result[name]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(sorted(repr(r) for r in rows)).encode()).hexdigest()}
  return result
for key,value in before['sqlite'].items():
 old=tables(Path(value['backup']));new=tables(root/key)
 result['sqlite'][key]={'changed_tables':changes(old,new),'before':old,'after':new}
allowed={'data/runtime/live/advisory/advisory_runtime.db','data/runtime/service.lock'}
result['protected_data_changes']=[k for k in result['data_changes'] if k not in allowed]
result['status']='PASS' if not result['legacy_changes'] and not result['workspace_changes'] and not result['protected_data_changes'] else 'FAIL'
for route in ('/healthz','/api/health','/api/live/stocks','/api/live/advisory/settings','/api/live/mode','/api/live/runtime-version'):
 with urllib.request.urlopen('http://127.0.0.1:8765'+route,timeout=20) as response:body=json.load(response)
 result['api'][route]=body
 (out/('real-'+route.strip('/').replace('/','-')+'.json')).write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')
result['settings_unchanged']=before['api']['/api/live/advisory/settings']==result['api']['/api/live/advisory/settings']
(out/'production-guard.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
code={}
for folder in ('app','adapters','bridges','contracts','engines','shared','tests','tools','docs','integrations','config'):
 for p in (root/folder).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts:code[p.relative_to(root).as_posix()]=digest(p)
for name in ('trading_lab.py','AGENTS.md','start_trading_lab.ps1'):code[name]=digest(root/name)
(out/'code-manifest.json').write_text(json.dumps({'before':before['code'],'after':code,'changes':changes(before['code'],code)},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:result[k] for k in ('status','legacy_count','legacy_changes','workspace_changes','data_changes','settings_unchanged')},ensure_ascii=True))
print('Changed tables:',{k:v['changed_tables'] for k,v in result['sqlite'].items() if v['changed_tables']})
