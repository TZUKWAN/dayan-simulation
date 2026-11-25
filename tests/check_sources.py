"""Static Python/JavaScript syntax and tracked-source hygiene; no bytecode writes."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def check_repository_hygiene(root=ROOT):
    """Inspect the index too: ignore rules alone cannot stop a forced staging."""
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    private_roots = ('.claude/', '.codex/', '.agents/', '.dsh/', 'dayan_runtime_data/')
    private = [name for name in tracked if name and (
        name.startswith(private_roots) or name.rsplit('/', 1)[-1] == '.workbench-token'
        or name == 'dayan/config.json' or name == '.env'
        or name.startswith('.env.') and name != '.env.example')]
    if private:
        raise RuntimeError('Private runtime/configuration files are staged or tracked: ' + ', '.join(private))


def main():
    check_repository_hygiene()
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
