"""Build a runtime-only offline artifact from an explicitly supplied sealed RC1.

No project, configuration, database or existing venv is accepted as input.
This packaging command is separate from the STEP 04 Portable builder.
"""
from pathlib import Path
import argparse, hashlib, json, stat, zipfile

ROOT = Path(__file__).resolve().parents[2]
def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--rc1',type=Path,required=True);a=p.parse_args()
    reference=ROOT/'portable-work/reference/rc1/runtime/files.json'
    seal=json.loads(reference.read_text('utf-8'))
    rows=[]
    for rel,digest in sorted(seal.items()):
        if not rel.startswith(('runtime/python/','runtime/node/')):continue
        source=a.rc1/rel
        for item in (source,*source.parents):
            if item.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:raise RuntimeError('Linked input')
        if sha(source)!=digest:raise RuntimeError('RC1 hash mismatch: '+rel)
        if source.stat().st_nlink!=1:raise RuntimeError('Hardlinked input')
        rows.append({'path':rel.removeprefix('runtime/'),'bytes':source.stat().st_size,'sha256':digest})
    if not rows:raise RuntimeError('Empty runtime')
    destination=ROOT/'.dev/artifacts';destination.mkdir(parents=True,exist_ok=True)
    artifact=destination/'tradinglab-dev-runtime-win-x64-20261011.1.zip'
    with zipfile.ZipFile(artifact,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for row in rows:
            info=zipfile.ZipInfo(row['path'],(2026,10,11,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            archive.writestr(info,(a.rc1/'runtime'/row['path']).read_bytes())
    dependencies=dict(line.split('==') for line in (ROOT/'requirements-lock.txt').read_text().splitlines() if '==' in line)
    lock={'schema':1,'artifact_version':'20261011.1','platform':'win32-x64','python':'3.12.14','node':'24.19.0',
          'artifact':{'filename':artifact.name,'bytes':artifact.stat().st_size,'sha256':sha(artifact),'download_url':None},
          'provenance':{'source':'Audited Portable RC1 runtime/python and runtime/node only','rc1_seal_sha256':sha(reference),'publisher_signature':'NOT_TESTED','acquisition':'Local artifact only; authenticated download reserved, not implemented'},
          'licenses':[r['path'] for r in rows if 'license' in r['path'].lower() or 'copying' in r['path'].lower()],
          'requirements_sha256':sha(ROOT/'requirements-lock.txt'),'dependencies':dependencies,'files':rows}
    folder=ROOT/'dev';folder.mkdir(exist_ok=True)
    (folder/'runtime-lock.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'artifact':str(artifact),'files':len(rows),'uncompressed_bytes':sum(r['bytes'] for r in rows),'sha256':sha(artifact)}))
if __name__=='__main__':main()
