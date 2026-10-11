"""Offline, reproducible developer venv. Never touches the current project's .venv."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,venv
ROOT=Path(__file__).resolve().parent
def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='从固定 Runtime 离线重建开发环境，不修改全局 Python。')
    p.add_argument('--target',type=Path,required=True);args=p.parse_args()
    if sys.version_info[:3]!=(3,12,14) or Path(sys.executable).resolve()!=(ROOT/'runtime/python/python.exe').resolve():raise SystemExit('Use bundled Python 3.12.14.')
    target=args.target.resolve()
    if not target.is_relative_to(ROOT.parent) or target.exists() or target in (ROOT,ROOT.parent):raise SystemExit('Use a NEW directory next to the portable release; no existing environment can be overwritten.')
    expected=json.loads((ROOT/'runtime/files.json').read_text(encoding='utf-8'))
    for rel,value in expected.items():
        if rel.startswith('runtime/python/'):
            with (ROOT/rel).open('rb') as f:
                if hashlib.file_digest(f,'sha256').hexdigest()!=value:raise SystemExit('Runtime integrity failure: '+rel)
    venv.EnvBuilder(with_pip=False,symlinks=False).create(target)
    shutil.copytree(ROOT/'runtime/python/Lib/site-packages',target/'Lib/site-packages',dirs_exist_ok=True)
    (target/'tradinglab-lock.json').write_text(json.dumps({'python':'3.12.14','runtime_manifest_sha256':hashlib.sha256((ROOT/'runtime/files.json').read_bytes()).hexdigest(),'requirements':(ROOT/'TradingLab/requirements-lock.txt').read_text()},indent=2),encoding='utf-8')
    print('开发环境已创建：'+str(target)+'\n依赖来自已校验 Runtime；无下载、无全局配置变更。目录移动后应重新创建此开发环境。')
if __name__=='__main__':main()
