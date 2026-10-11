"""Storage mechanics only: checked paths and bounded, verified SQLite snapshots."""
from pathlib import Path
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib,json,sqlite3,shutil,os,stat

def checked(root,path):
    root=Path(root).absolute();path=Path(path).absolute()
    if root.resolve()!=root:raise ValueError('MAINTENANCE_REPARSE_POINT')
    if not path.is_relative_to(root):raise ValueError('MAINTENANCE_PATH_OUTSIDE_OWNER')
    for p in (root,*reversed(path.relative_to(root).parents)):
        p=p if p.is_absolute() else root/p
        if p.exists() and (p.is_symlink() or getattr(p.stat(follow_symlinks=False),'st_file_attributes',0)&1024):raise ValueError('MAINTENANCE_REPARSE_POINT')
    if path.exists() and (path.is_symlink() or getattr(path.stat(follow_symlinks=False),'st_file_attributes',0)&1024):raise ValueError('MAINTENANCE_REPARSE_POINT')
    return path

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def compact_database(root,path):
    """Offline owner call only: exclusive connection, same logical rows, no copy."""
    path=checked(root,path)
    if shutil.disk_usage(path.parent).free<path.stat().st_size*2+64*1024*1024:raise ValueError('COMPACTION_SPACE_REQUIRED')
    def logical(db):
        schema=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        values={}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            rows=db.execute('SELECT * FROM "'+table.replace('"','""')+'"').fetchall()
            encoded=sorted(json.dumps(r,ensure_ascii=False,default=lambda b:{'hex':b.hex()},separators=(',',':')) for r in rows)
            values[table]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
        return {'schema':schema,'tables':values}
    with closing(sqlite3.connect(path,timeout=2,isolation_level=None)) as db:
        db.execute('PRAGMA locking_mode=EXCLUSIVE');db.execute('BEGIN EXCLUSIVE');db.execute('COMMIT')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('COMPACTION_INTEGRITY_FAILED')
        before=logical(db);size=path.stat().st_size
        free=db.execute('PRAGMA freelist_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
        if free:db.execute('VACUUM')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or logical(db)!=before:raise ValueError('COMPACTION_LOGICAL_MISMATCH')
    return {'path':str(path),'before_bytes':size,'after_bytes':path.stat().st_size,'released_bytes':size-path.stat().st_size,'logical_data_unchanged':True,'integrity':'ok'}

def snapshot_preflight(root,files,*,cap,max_count,valid_days):
    """Readonly prerequisite check; never creates a snapshot or rotates files."""
    try:
        root=checked(Path(root),Path(root));needed=0
        for path in files.values():
            path=checked(root,path)
            if not path.is_file():raise ValueError('OWNER_DATABASE_MISSING')
            with path.open('rb') as stream:stream.read(1)
            needed+=path.stat().st_size
        parent=checked(root,root/'maintenance-backups');used=0;complete=[];verified_runs=[]
        if parent.exists():
            for folder in parent.iterdir():
                checked(root,folder)
                if not folder.is_dir():raise ValueError('BACKUP_UNKNOWN_CONTENT')
                for p in folder.iterdir():
                    checked(root,p)
                    if not p.is_file():raise ValueError('BACKUP_UNKNOWN_CONTENT')
                    used+=p.stat().st_size
                manifest=folder/'manifest.json'
                if manifest.exists():
                    value=json.loads(manifest.read_text(encoding='utf-8'))
                    if {p.name for p in folder.iterdir()}!=set(value['files'])|{'manifest.json'}:raise ValueError('BACKUP_UNKNOWN_CONTENT')
                    for name,item in value['files'].items():
                        if sha(checked(folder,folder/name))!=item['sha256']:raise ValueError('BACKUP_HASH_MISMATCH')
                    complete.append(value)
                    verified_runs.append(folder.name)
        reclaimable=sum(sum(f['bytes'] for f in v['files'].values()) for v in complete[:-1] if not v.get('protected_until') or datetime.fromisoformat(v['protected_until'])<=datetime.now(timezone.utc))
        free=shutil.disk_usage(root).free
        if needed>cap or used+needed-reclaimable>cap or free<needed+64*1024*1024:raise ValueError('BACKUP_SPACE_REQUIRED')
        return {'status':'PASSED','required_bytes':needed,'existing_bytes':used,'free_bytes':free,'cap_bytes':cap,'snapshot_status':'NOT_CREATED','verified_runs':verified_runs,'first_protection_days':valid_days,'max_count':max_count}
    except (OSError,ValueError,KeyError) as e:return {'status':'FAILED','reason':str(e) if isinstance(e,ValueError) else type(e).__name__,'root':str(root)}

def snapshot(root,files,run_id,*,cap,max_count,valid_days):
    """Never removes an only snapshot. Deletion is manifest-listed files, no tree walk."""
    if max_count<2 or valid_days<1:raise ValueError('RECOVERABLE_SNAPSHOT_LIMIT_INVALID')
    root=Path(root);destination=checked(root,root/'maintenance-backups'/run_id);manifest=destination/'manifest.json'
    def verify(folder):
        value=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        for name,item in value['files'].items():
            if sha(checked(folder,folder/name))!=item['sha256']:raise ValueError('BACKUP_HASH_MISMATCH')
        return value
    if manifest.exists():return verify(destination)
    paths={name:checked(root,p) for name,p in files.items() if Path(p).exists()}
    needed=sum(p.stat().st_size for p in paths.values())
    existing=[p for p in (root/'maintenance-backups').glob('*') if p.is_dir() and (p/'manifest.json').exists()]
    # At most two complete copies including new snapshot; refuse oversized owner.
    if needed>cap or shutil.disk_usage(root).free<needed+64*1024*1024:raise ValueError('BACKUP_SPACE_REQUIRED')
    existing.sort(key=lambda p:p.name)
    now=datetime.now(timezone.utc)
    def pinned(value):return bool(value.get('protected_until') and datetime.fromisoformat(value['protected_until'])>now)
    def remove_known(folder,value):
        if {p.name for p in folder.iterdir()}!=set(value['files'])|{'manifest.json'}:return False
        for name in value['files']:checked(root,folder/name).unlink()
        checked(root,folder/'manifest.json').unlink();folder.rmdir();return True
    # Count incomplete snapshots too. An interrupted copy cannot silently sit
    # outside the quota; the same run resumes by replacing its incomplete DB.
    used=0
    parent=root/'maintenance-backups'
    if parent.exists():
        for folder in parent.iterdir():
            checked(root,folder)
            if not folder.is_dir():raise ValueError('BACKUP_UNKNOWN_CONTENT')
            for item in folder.iterdir():
                checked(root,item)
                if not item.is_file():raise ValueError('BACKUP_UNKNOWN_CONTENT')
                used+=item.stat().st_size
    while used+needed>cap and len(existing)>1:
        old=next((p for p in existing if not pinned(verify(p))),None)
        if old is None:raise ValueError('PROTECTED_BACKUP_CAPACITY_REQUIRED')
        prior=verify(old)
        if not remove_known(old,prior):raise ValueError('BACKUP_UNKNOWN_CONTENT')
        used-=sum(f['bytes'] for f in prior['files'].values());existing.remove(old)
    if used+needed>cap:raise ValueError('BACKUP_SPACE_REQUIRED')
    destination.mkdir(parents=True,exist_ok=True);entries={}
    for name,path in paths.items():
        target=checked(destination,destination/name)
        if '/' in name or '\\' in name:raise ValueError('BACKUP_NAME_INVALID')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(target)) as dest:
            source.backup(dest,pages=128,sleep=.02)
            if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('BACKUP_INTEGRITY_FAILED')
        entries[name]={'sha256':sha(target),'bytes':target.stat().st_size}
    value={'created_at':now.isoformat(),'protected_until':(now+timedelta(days=valid_days)).isoformat() if not existing else None,
           'rotation_max_count':max_count,'files':entries,'cap_bytes':cap,'restore_requires_offline_and_no_newer_writes':True}
    temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(manifest);verify(destination)
    remaining=[*existing,destination]
    for old in existing:
        if len(remaining)<=max_count:break
        prior=verify(old)
        if not pinned(prior) and remove_known(old,prior):remaining.remove(old)
    return value
