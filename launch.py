"""Desktop entry point: readiness check, browser opening and readable diagnostics."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:8000/'


def main():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def ready():
        try:
            with opener.open(URL+'api/dashboard',timeout=1) as response:
                return response.status==200
        except Exception:
            return False
    if ready():
        print('Service already running. Opening browser.')
        webbrowser.open(URL)
        return
    log=ROOT/'data'/'service.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.Popen([sys.executable,'-u','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000'],
                                 cwd=ROOT,env=dict(os.environ,PYTHONUNBUFFERED='1'),stdout=output,stderr=subprocess.STDOUT)
        try:
            print('Starting service; checking readiness for up to 30 seconds...',flush=True)
            deadline=time.monotonic()+30
            while process.poll() is None and time.monotonic()<deadline:
                if ready():
                    print('READY: '+URL+'  Keep this window open. Ctrl+C to stop.',flush=True)
                    webbrowser.open(URL)
                    process.wait()
                    return
                time.sleep(.5)
            output.flush()
            print('STARTUP FAILED. Check port 8000 and the following log:',flush=True)
            print(log.read_text(encoding='utf-8',errors='replace'),flush=True)
            print('Log file: '+str(log))
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill()


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('Stopped.')
    except Exception as exc: print('LAUNCH ERROR: '+str(exc)); raise SystemExit(1)
