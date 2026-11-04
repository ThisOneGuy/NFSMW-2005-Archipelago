          

from pathlib import Path
import hashlib
import json
import os
import sys
import traceback

def main():
    game=Path(__file__).resolve().parent
    data=game/'NFSMWClient_Data'
    log_root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'NFSMWArchipelago'
    log_root.mkdir(parents=True,exist_ok=True)
    stream=None
    for name in ('stdout','stderr'):
        if getattr(sys,name) is None:
            if stream is None:stream=(log_root/'desktop.log').open('a',encoding='utf-8',buffering=1)
            setattr(sys,name,stream)
    if sys.stdin is None:sys.stdin=open(os.devnull,encoding='utf-8')
    try:
        if sys.platform!='win32' or not (3,11)<=sys.version_info[:2]<=(3,13) or sys.maxsize<2**32:
            raise RuntimeError('This entry requires standard 64-bit Windows Python 3.11, 3.12 or 3.13 with Tcl/Tk. Open this .pyw file with Python (windowed).')
        manifest=json.loads((data/'bundle.json').read_text(encoding='utf-8'))
        payload=(data/'app.zip').read_bytes();expected=manifest['files']['app.zip']
        if len(payload)!=expected['bytes'] or hashlib.sha256(payload).hexdigest()!=expected['sha256']:
            raise RuntimeError('The client modules do not match bundle.json. Extract the full update together.')
        sys.path.insert(0,str(data/'app.zip'))
        from NFSMW_PythonBootstrap import run
        run(game,data,log_root)
    except SystemExit as exc:
        if exc.code not in (None,0):raise
    except Exception as exc:
        traceback.print_exc()
        message=f'Could not open NFSMW Client: {exc}\n\nDetails: {log_root / "desktop.log"}'
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,'NFSMW Python Client',0x10)
        else:print(message,file=sys.stderr)

if __name__=='__main__':main()
