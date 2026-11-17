"""Static Python/JavaScript syntax and tracked-source hygiene; no bytecode writes."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    count=0
    for directory in ('dayan','src','experiments','tests'):
        for path in (ROOT/directory).rglob('*.py'):
            if '__pycache__' in path.parts:continue
            compile(path.read_bytes(),str(path),'exec');count+=1
    node=shutil.which('node')
    if not node:raise RuntimeError('Node.js is required to verify frontend/plugin syntax')
    scripts=list((ROOT/'site/console').glob('*.js'))+list((ROOT/'plugins/dayan').rglob('*.js'))
    for path in scripts:subprocess.run([node,'--check',str(path)],check=True,capture_output=True)
    print(f'Python syntax: {count} files; JavaScript syntax: {len(scripts)} files')
    return 0


if __name__=='__main__':sys.exit(main())
