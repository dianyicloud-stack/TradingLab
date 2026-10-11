"""Read-only comparison against this round's captured production baseline."""
from pathlib import Path
import hashlib,json,sqlite3,urllib.request
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/m2_ai_closure'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inventory(root):return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def main():
    before=json.loads((OUT/'before/protected.json').read_text(encoding='utf-8'))
    after={'files':{'legacy':inventory(ROOT/'legacy'),'v2a_workspace':inventory(ROOT.parent/'TradingLabData/V2AWorkspace'),
                    'formal':inventory(ROOT/'data/decisions/live_bridge'),'source_config':digest(ROOT/'data/system/market-source.json')},'tables':{}}
    for name in before['tables']:
        with sqlite3.connect((ROOT/name).as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON');tables={}
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                rows=db.execute('SELECT * FROM "'+table.replace('"','""')+'"').fetchall()
                tables[table]={'count':len(rows),'hash':hashlib.sha256('\n'.join(sorted(repr(r) for r in rows)).encode()).hexdigest()}
            after['tables'][name]=tables
    changes=[name for name in before['files'] if before['files'][name]!=after['files'][name]]
    changes += [name for name in before['tables'] if before['tables'][name]!=after['tables'][name]]
    old_cursors=json.loads((OUT/'before/advisory_cursors.json').read_text(encoding='utf-8'))
    candidates=list((ROOT/'data/runtime/live').rglob('advisory_runtime.db'))
    candidates=[p for p in candidates if 'test' not in str(p).lower()]
    # The production runtime path is resolved from the actual existing table file.
    if len(candidates)!=1:raise RuntimeError('Ambiguous production runtime path')
    with sqlite3.connect(candidates[0].as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        cursors=[dict(row) for row in db.execute('SELECT * FROM advisory_cursors')]
    if sorted(cursors,key=lambda r:r['tracking_session_id'])!=sorted(old_cursors,key=lambda r:r['tracking_session_id']):changes.append('advisory_success_cursors')
    with urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=10) as response:health=json.load(response)
    old_health=json.loads((OUT/'before/healthz.json').read_text(encoding='utf-8'))
    report={'status':'PASS' if not changes else 'FAIL','changes':changes,'legacy_count':len(after['files']['legacy']),
            'protected_table_files':len(after['tables']),'web_same_instance':health.get('instance_id')==old_health.get('instance_id'),
            'note':'Agent owner may continue committing its own market facts; not asserted immutable.'}
    (OUT/'protected-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'production-guard.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if not changes else 1
if __name__=='__main__':raise SystemExit(main())
