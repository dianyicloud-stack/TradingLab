"""Read-only production comparison and archive inventory. Never initializes an owner."""
from pathlib import Path
import hashlib,json,sqlite3,re
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/m2_auto_agent_closure'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def files(root):return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def tables(path):
    result={}
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            rows=[]
            for row in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'):rows.append(hashlib.sha256(repr(row).encode()).hexdigest())
            result[name]={'count':len(rows),'sha256':hashlib.sha256(''.join(sorted(rows)).encode()).hexdigest()}
    return result
def main():
    before=json.loads((OUT/'before/guard.json').read_text(encoding='utf-8'));old=(ROOT.parent/'TradingLabData/V2AWorkspace').resolve()
    inventory={k:files(v) for k,v in {'legacy':ROOT/'legacy','v2a':old,'formal':ROOT/'data/decisions/live_bridge'}.items()}
    changes={k:[name for name in set(before[k])|set(current) if before[k].get(name)!=current.get(name)] for k,current in inventory.items()}
    database_changes={};counts={}
    for name in before['db']:
        a=tables(OUT/'before/db'/name);b=tables(ROOT/name);changed=[key for key in set(a)|set(b) if a.get(key)!=b.get(key)]
        if changed:database_changes[name]=changed
        counts[name]=b
    source_ids=set()
    for path in old.rglob('*'):
        if path.is_file() and path.suffix in ('.json','.jsonl'):
            source_ids.update(re.findall(r'(?:TS-\d{8}-[a-z]{2}\d{6}-\d+|(?:E?HO)-\d{8}-[A-Za-z0-9-]+)',path.read_text(encoding='utf-8-sig')))
    identity_pattern=re.compile('|'.join(re.escape(s) for s in sorted(source_ids))) if source_ids else None
    references=[];modes=[]
    # The captured immutable audit copies are sufficient for reference discovery.
    for path in (OUT/'before/db').rglob('*.db'):
        if 'tracking-deletions' in path.parts:continue
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                matched=0
                for row in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'):
                    if any(isinstance(v,str) and ('V2AWorkspace' in v or 'V2A_WORKSPACE' in v or identity_pattern and identity_pattern.search(v)) for v in row):matched+=1
                if matched:references.append({'snapshot':str(path.relative_to(OUT/'before/db')),'table':name,'referencing_rows':matched,'action':'PRESERVE_IMMUTABLE_HISTORY_AND_ARCHIVE_SOURCE_FILES'})
            if path.name=='account.db':
                row=db.execute('SELECT body FROM projection WHERE id=1').fetchone()
                if row:
                    value=json.loads(row[0])
                    if value.get('account_type')=='LIVE_SHADOW':modes.append({'account_type':'LIVE_SHADOW','namespace':value.get('namespace'),'ai_execution_mode':value.get('policy',{}).get('ai_execution_mode')})
    report={'at':datetime.now(timezone.utc).isoformat(),'status':'PASS' if not any(changes.values()) and not database_changes else 'FAIL',
        'files_changes':changes,'database_changes':database_changes,'legacy_count':len(inventory['legacy']),'database_files_checked':len(counts),
        'account_modes_from_readonly_snapshot':modes,'old_workspace':{'resolved_path':str(old),'exists':old.exists(),'is_symlink':old.is_symlink(),
            'files':[{'path':str(p.relative_to(old)),'bytes':p.stat().st_size,'sha256':digest(p)} for p in old.rglob('*') if p.is_file()],
            'proposed_archive':str(ROOT.parent/'TradingLabData/HistoricalArchives/V2AWorkspace-20260918'),
            'physical_deletion':'NOT_AUTHORIZED_NOT_EXECUTED','active_external_writer':'NOT_PROVEN_BY_OS_HANDLE_INSPECTION','source_identity_index':sorted(source_ids)},'historical_references':references,
        'note':'Account/Learning/Formal/Opinion/Input/Provider attempts/Live settings/success cursors compared as read-only table contents; Agent may independently append market facts.'}
    (OUT/'production-guard.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'production-table-hashes.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','files_changes','database_changes','legacy_count','database_files_checked','account_modes_from_readonly_snapshot')},ensure_ascii=False))
if __name__=='__main__':main()
