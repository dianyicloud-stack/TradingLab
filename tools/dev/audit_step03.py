"""Read-only protected-root comparison; write only local STEP03 evidence."""
from pathlib import Path
import difflib, hashlib, json, re, shutil, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/migration'))
import step02_audit as a
OUT=ROOT/'docs/migration/step03'
OUT.mkdir(parents=True,exist_ok=True)
def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def run():
    before=json.loads((ROOT/'.dev/evidence/before.json').read_text('utf-8'))
    after={key:a.metadata_snapshot(a.walk(Path(key)),Path(key)) for key in before['roots']}
    equality={key:before['roots'][key]==after[key] for key in after}
    if not all(equality.values()):raise RuntimeError('PROTECTED_ROOT_CHANGED')
    reference=json.loads((ROOT/'portable-work/reference/rc1/runtime/files.json').read_text('utf-8'))
    errors=[rel for rel,expected in reference.items() if a.sha(a.PORTABLE/rel)!=expected]
    if errors:raise RuntimeError('RC1_HASH_CHANGED')
    save('protected-roots.json',{'before':before['roots'],'after':after,'equal':equality,'step01':a.baseline_check(),'rc1_sealed_files':len(reference),'rc1_hash_differences':errors,'method':'All protected files path/bytes/mtime_ns/file_id compared. Formal databases not opened. STEP01/RC1 sealed static files also SHA-256 verified.'})
    old=json.loads((ROOT/'docs/migration/step02/unified-file-manifest.json').read_text('utf-8'))
    originals={r['path']:r for r in old['files']}
    current={p.relative_to(ROOT).as_posix():p for p in a.walk(ROOT) if not any(x in p.relative_to(ROOT).parts for x in ('.dev','.venv'))}
    modified=[];missing=[]
    for rel,row in originals.items():
        if rel not in current:missing.append(rel)
        elif a.sha(current[rel])!=row['sha256']:modified.append({'path':rel,'before_sha256':row['sha256'],'after_sha256':a.sha(current[rel])})
    business=[rel for rel in originals if rel.split('/')[0] in a.CORE or rel in ('trading_lab.py','market_data_agent.py')]
    tests=[rel for rel in originals if rel.startswith('tests/')]
    legacy=[rel for rel in originals if rel.startswith('legacy/')]
    changed={row['path'] for row in modified}
    assert not (set(business+tests+legacy)&(changed|set(missing)))
    save('source-preservation.json',{'business_files_unchanged':len(business),'test_files_unchanged':len(tests),'legacy_files_unchanged':len(legacy),'missing_step02_payload':missing,'modified':modified,'new_files':[rel for rel in sorted(current) if rel not in originals and rel not in old['self_index_excluded']]})
    patches=[]
    for row in modified:
        rel=row['path'];source=a.SOURCE/rel
        if source.is_file() and a.sha(source)==row['before_sha256']:
            patches.extend(difflib.unified_diff(source.read_text('utf-8-sig').splitlines(True),current[rel].read_text('utf-8-sig').splitlines(True),fromfile='STEP02/'+rel,tofile='STEP03/'+rel))
    (OUT/'tool-path-changes.patch').write_text(''.join(patches),encoding='utf-8')
    scan=[]
    for rel,p in current.items():
        if p.suffix.lower() not in ('.py','.js','.mjs','.cjs','.ps1','.cmd','.json','.yaml','.yml','.md','.txt','.html','.css') and not rel.startswith('.env'):continue
        for name,pattern in a.PATTERNS.items():
            for number,line in enumerate(p.read_text('utf-8-sig',errors='replace').splitlines(),1):
                if pattern.search(line):scan.append({'path':rel,'line':number,'kind':name})
    save('sensitive-scan.json',{'scope':'All non-generated source/docs/locks; excludes .dev/.venv private diagnostics. No source credential values read/exported. Empty DEV env checked separately; artifact contents restricted to audited sealed Runtime paths.','findings':scan,'fixed_telegram_recipient':'Known business-source personal recipient remains; no value reproduced; TEST disabled; pending controlled remediation.','production_account_isolation':'New TEST stores under .dev only; no production database connected; protected metadata unchanged.'})
    evidence=ROOT/'.dev/validation'
    for name in ('results.jsonl','unittest.log','baselines.log','final-startup-failure-rollback.log','final-boundary-guard.log','final-chinese-start.log','final-chinese-stop.log','final-chinese-check.log','missing-artifact.log','corrupt-artifact.log','zip-traversal.log','zip-absolute.log','zip-symlink.log','zip-unexpected.log','venv-unlisted-file.log','runtime-corruption.log','port-occupied.log','unknown-data-roots.log','nonempty-credential-config.log','final-fresh-setup.log','chinese-setup-poisoned-system.log','chinese-setup-repeat.log'):
        shutil.copyfile(evidence/name,OUT/name)
    shutil.copyfile(ROOT/'.dev/evidence/live-services.json',OUT/'live-services.json')
    shutil.copyfile(ROOT/'.dev/tool-dependencies.json',OUT/'tool-dependencies.json')
    shutil.copyfile(ROOT/'.dev/evidence/tool-syntax.json',OUT/'tool-syntax.json')
    shutil.copyfile(ROOT/'.dev/evidence/process-isolation.json',OUT/'process-isolation.json')
    lock=json.loads((ROOT/'dev/runtime-lock.json').read_text('utf-8'));artifact=ROOT/'.dev/artifacts'/lock['artifact']['filename']
    assert a.sha(artifact)==lock['artifact']['sha256']
    save('runtime-artifact.json',{'path':str(artifact),'artifact':lock['artifact'],'files':len(lock['files']),'uncompressed_bytes':sum(r['bytes'] for r in lock['files']),'dependencies':lock['dependencies'],'license_file_count':len(lock['licenses'])})
    print(json.dumps({'protected_roots':'PASS','rc1_hashes':len(reference),'business':len(business),'tests':len(tests),'legacy':len(legacy),'modified':len(modified),'secret_shape_findings':len(scan)},ensure_ascii=False))
if __name__=='__main__':run()
