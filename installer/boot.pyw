import os
import runpy
import sys

data = os.path.dirname(os.path.abspath(__file__))
runtime = os.path.join(data, "runtime")
dll_directories = [
    os.add_dll_directory(runtime),
    os.add_dll_directory(os.path.join(runtime, "DLLs")),
]
sys._nfsmw_game_root = os.path.dirname(data)
sys._nfsmw_entry_name = "client.exe"
sys._MEIPASS = data
sys._nfsmw_client_runtime = True
sys.frozen = True
try:
    runpy.run_path(os.path.join(data, "verify_install.pyw"))["verify"](os.path.dirname(data))
except Exception as exc:
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        None,
        "Could not open NFSMW Client: "
        + str(exc)
        + "\n\nExtract the complete manual package beside speed.exe, or run NFSMW Setup to repair it.",
        "NFSMW Client",
        0x10,
    )
    raise SystemExit(1)
from NFSMW_Standalone import entrypoint

entrypoint()
