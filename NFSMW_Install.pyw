from pathlib import Path
import sys

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'NFSMWClient_Data/app.zip'))
try:
    from NFSMW_PythonInstall import main
    main(root)
except Exception as exc:
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.withdraw()
    messagebox.showerror('NFSMW Client Setup',str(exc),parent=window)
    window.destroy()
