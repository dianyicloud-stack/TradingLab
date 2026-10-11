"""Explicit local code snapshots/diffs; never scans production data or credentials."""
from pathlib import Path
import hashlib,json,difflib,sys,shutil
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/m2_auto_agent_closure'
def record(stage):
    before=OUT/({'A':'before/code','B':'A/code','C':'B/code'}[stage])
    after=OUT/stage/'code';after.mkdir(parents=True,exist_ok=True)
    paths=[]
    for folder in ('app','adapters','bridges','contracts','engines','shared','config','docs','scripts'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.db'))
    for folder in ('tests','tools'):
        paths.extend(p for p in (ROOT/folder).iterdir() if p.is_file() and p.suffix in ('.py','.js','.json'))
    paths.extend(p for p in ROOT.iterdir() if p.is_file() and p.suffix in ('.py','.ps1','.md','.txt','.yaml'))
    paths.extend((ROOT/'tests/fixtures').glob('agent_low_volume_*.json'))
    rows=[];diff=[]
    for p in sorted(set(paths)):
        rel=p.relative_to(ROOT);dest=after/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
        old=before/rel;a=old.read_bytes() if old.exists() else b'';b=p.read_bytes()
        if a==b:continue
        rows.append({'path':rel.as_posix(),'before_sha256':hashlib.sha256(a).hexdigest() if old.exists() else None,'after_sha256':hashlib.sha256(b).hexdigest()})
        try:diff.extend(difflib.unified_diff(a.decode('utf-8-sig').splitlines(True),b.decode('utf-8-sig').splitlines(True),fromfile='before/'+rel.as_posix(),tofile='after/'+rel.as_posix()))
        except UnicodeError:pass
    (OUT/stage/'manifest.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (OUT/stage/'changes.patch').write_text(''.join(diff),encoding='utf-8')
    print(json.dumps({'stage':stage,'changed_files':len(rows),'path':str(OUT/stage)}))
if __name__=='__main__':record(sys.argv[1])
