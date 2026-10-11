"""Read-only owner-aware audit. Differences are evidence, never reset to PASS."""
from pathlib import Path
import hashlib,json,sqlite3,datetime
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/m2_runtime_closure'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
before=json.loads((OUT/'before/protected.json').read_text());source=json.loads((OUT/'before/_api_system_market-source.json').read_text(encoding='utf-8'))
files={'legacy':inventory(ROOT/'legacy'),'v2a_workspace':inventory(Path(source['configuration']['v2a_workspace'])),
       'formal':inventory(ROOT/'data/decisions/live_bridge'),'data/system/market-source.json':digest(ROOT/'data/system/market-source.json')}
tables={}
for root in [ROOT/'data/account',ROOT/'data/learning',ROOT/'data/decisions']:
    for p in root.rglob('*.db'):
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');tables[str(p.relative_to(ROOT))]={}
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                rows=db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall()
                tables[str(p.relative_to(ROOT))][name]={'count':len(rows),'hash':hashlib.sha256('\n'.join(sorted(map(repr,rows))).encode()).hexdigest()}
changes={}
for key,old in before['files'].items():
    new=files[key];changes[key]=([p for p in sorted(set(old)|set(new)) if old.get(p)!=new.get(p)] if isinstance(old,dict) else old!=new)
table_changes=[]
for path in sorted(set(before['tables'])|set(tables)):
    old=before['tables'].get(path,{});new=tables.get(path,{})
    for name in sorted(set(old)|set(new)):
        if old.get(name)!=new.get(name):table_changes.append({'path':path,'table':name,'before':old.get(name),'after':new.get(name)})
report={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'file_changes':changes,'table_changes':table_changes,
        'status':'UNCHANGED' if not any(changes.values()) and not table_changes else 'DIFFERENCES_RECORDED',
        'interpretation':'Active production may append its own facts. No test/AI/trade command was sent to production; differences are not silently attributed or accepted.',
        'historical_failures_preserved':['artifacts/market_agent/production-guard.json'],
        'agent_market_database':'Not treated as immutable: existing producer continues its normal collection.'}
(OUT/'production-protection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':report['status'],'file_changes':changes,'changed_tables':len(table_changes)},ensure_ascii=False))
