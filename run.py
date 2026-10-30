"""Build and run the complete local application. Python 3.12+, Node 22+."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import venv
import webbrowser
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
BACKEND=ROOT/'backend'
FRONTEND=ROOT/'frontend'

def command(args,cwd=ROOT):
    subprocess.run([str(a) for a in args],cwd=cwd,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='Run pytest and the production build, then exit')
    parser.add_argument('--python',help='Use an existing project Python environment')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    node=shutil.which('node')
    if not node: raise SystemExit('Node.js 22+ is required. Install Node.js LTS, then run again.')
    if not args.check:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',args.port))==0:
                raise SystemExit(f'Port {args.port} is occupied. Close the existing TimeSync process or use --port 8001.')
    envdir=ROOT/'.venv'
    if args.python:
        python=Path(args.python).resolve()
    else:
        python=envdir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not python.exists(): venv.create(envdir,with_pip=True)
    requirements=BACKEND/'requirements.txt'
    stamp=python.parent.parent/'.timesync-requirements.sha256'
    digest=hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not stamp.exists() or stamp.read_text()!=digest:
        command([python,'-m','pip','install','-r',requirements])
        stamp.write_text(digest)
    if not (ROOT/'.env').exists(): shutil.copy(ROOT/'.env.example',ROOT/'.env')
    pnpm=shutil.which('pnpm')
    npm=shutil.which('npm')
    bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pnpm/bin/pnpm.mjs'
    package_command=[pnpm] if pnpm else [node,bundled] if bundled.exists() else [npm] if npm else None
    if not package_command: raise SystemExit('npm or pnpm is required. A standard Node.js installation includes npm.')
    package_stamp=FRONTEND/'node_modules'/'.timesync-lock.sha256'
    package_digest=hashlib.sha256((FRONTEND/'pnpm-lock.yaml').read_bytes()).hexdigest()
    if not package_stamp.exists() or package_stamp.read_text()!=package_digest:
        # Platform-specific esbuild binaries are normal optional dependencies.
        # No dependency lifecycle scripts are required for this Vite project.
        command(package_command+['install','--ignore-scripts']+(['--frozen-lockfile'] if not npm or package_command!=[npm] else []),FRONTEND)
        package_stamp.write_text(package_digest)
    command([node,FRONTEND/'node_modules/typescript/bin/tsc','-b'],FRONTEND)
    command([node,FRONTEND/'node_modules/vite/bin/vite.js','build'],FRONTEND)
    if args.check:
        command([node,'--experimental-strip-types','--test','tests/calendar.test.mjs'],FRONTEND)
        command([python,'-m','pytest','-q'],BACKEND)
        print('TimeSync: backend tests, TypeScript and production build passed.')
        return
    print(f'TimeSync: http://127.0.0.1:{args.port} | API: /docs | Ctrl+C to stop',flush=True)
    server=subprocess.Popen([str(p) for p in [python,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',args.port]],cwd=BACKEND)
    try:
        for _ in range(150):
            if server.poll() is not None: raise SystemExit('Backend failed to start. See the error above.')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/api/health',timeout=1) as response:
                    if response.status==200: break
            except OSError: time.sleep(.2)
        else: raise SystemExit('Backend startup timed out.')
        if not args.no_browser: webbrowser.open(f'http://127.0.0.1:{args.port}')
        server.wait()
    except KeyboardInterrupt:
        print('\nTimeSync stopped. Database preserved.')
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=10)

if __name__=='__main__':
    try: main()
    except subprocess.CalledProcessError as error: raise SystemExit(error.returncode)
