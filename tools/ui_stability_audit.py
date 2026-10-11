"""Read-only production evidence; outputs belong only to this acceptance run."""
from pathlib import Path
import hashlib,json,sqlite3,time,urllib.request,shutil,sys,platform
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ui_stability'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):return {p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def main():
    phase=sys.argv[1] if len(sys.argv)>1 else 'before'
    out=OUT/phase;out.mkdir(parents=True,exist_ok=True)
    report={'machine':platform.platform(),'python':sys.version,'time':time.time(),'files':{},'sqlite':{},'api':{}}
    for name,root in [('legacy',ROOT/'legacy'),('workspace',ROOT.parent/'TradingLabData/V2AWorkspace')]:report['files'][name]=inventory(root)
    # Production Agent is live: capture schema/table counts without claiming its ongoing facts are immutable.
    for root in [ROOT/'data',ROOT.parent/'TradingLabData/MarketDataAgent']:
        for p in root.rglob('*.db'):
            with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=10) as db:
                db.execute('PRAGMA query_only=ON');tables={}
                for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    rows=db.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall()
                    tables[name]={'count':len(rows),'sha256':hashlib.sha256('\n'.join(sorted(repr(r) for r in rows)).encode()).hexdigest()}
                report['sqlite'][str(p)]={'user_version':db.execute('PRAGMA user_version').fetchone()[0],'tables':tables}
    for route in ['/healthz','/api/system/market-source','/api/live/runtime-version','/api/live/stocks','/api/live/advisory/settings','/api/data-observation/state','/api/health','/system']:
        timings=[]
        for _ in range(3):
            start=time.perf_counter()
            with urllib.request.urlopen('http://127.0.0.1:8765'+route,timeout=90) as response:body=response.read()
            timings.append(round((time.perf_counter()-start)*1000,2))
        report['api'][route]={'ms':timings,'bytes':len(body)}
        (out/(route.strip('/').replace('/','-')+('.html' if route=='/system' else '.json'))).write_bytes(body)
    if phase=='before':
        for folder in ['app','adapters','bridges','engines','contracts','shared']:
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:
                    target=out/'code'/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'phase':phase,'api':report['api'],'legacy_count':len(report['files']['legacy'])},ensure_ascii=False))
if __name__=='__main__':main()
