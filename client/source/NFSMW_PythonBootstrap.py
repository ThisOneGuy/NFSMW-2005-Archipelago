from __future__ import annotations
import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

REQUIREMENTS = (
    "colorama==0.4.6",
    "websockets==13.1",
    "PyYAML==6.0.3",
    "schema==0.7.8",
    "platformdirs==4.10.1",
    "certifi==2026.10.23",
    "typing_extensions==4.15.0",
    "jellyfish==1.2.1",
    "orjson==3.11.7",
    "pathspec==1.0.4",
)


def dependencies_ready():
    for requirement in REQUIREMENTS:
        name, version = requirement.split("==")
        try:
            if importlib.metadata.version(name) != version:
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
    return True


def install_command(target):
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--only-binary=:all:",
        "--index-url",
        "https://pypi.org/simple",
        "--upgrade",
        "--target",
        str(target),
        *REQUIREMENTS,
    ]


def start_dependency_install(target, stream):
    return subprocess.Popen(
        install_command(target),
        stdout=stream,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        shell=False,
    )


def prepare_dependencies(log_root):
    target = Path(log_root) / "Python" / sys.implementation.cache_tag / "site-packages"
    sys.path.insert(0, str(target))
    if dependencies_ready():
        return
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("NFSMW Python Client Setup")
    root.geometry("610x300")
    root.resizable(False, False)
    text = tk.StringVar(
        value="Install the client's pinned Python dependencies into its own local folder?\n\nYour system packages, game saves and antivirus settings are unchanged.\nNo command window is needed. Python with pip and Tcl/Tk is required."
    )
    tk.Label(root, textvariable=text, justify="left", wraplength=565, padx=20, pady=24).pack(
        fill="x"
    )
    state = {"process": None, "stream": None, "success": False}

    def poll():
        code = state["process"].poll()
        if code is None:
            root.after(150, poll)
            return
        state["stream"].close()
        state["stream"] = None
        if code == 0:
            state["success"] = True
            root.destroy()
        else:
            text.set(
                "Dependency setup failed. Details are in:\n"
                + str(Path(log_root) / "python_setup.log")
                + "\n\nYou can retry or cancel."
            )
            install.config(state="normal")

    def start():
        if state["process"] is not None and state["process"].poll() is None:
            return
        if importlib.util.find_spec("pip") is None:
            messagebox.showerror(
                "Python pip is missing",
                "Use the standard Python installer to add pip, then reopen NFSMWClient.pyw.",
                parent=root,
            )
            return
        target.mkdir(parents=True, exist_ok=True)
        state["stream"] = (Path(log_root) / "python_setup.log").open("a", encoding="utf-8")
        try:
            state["process"] = start_dependency_install(target, state["stream"])
        except OSError as exc:
            state["stream"].close()
            state["stream"] = None
            messagebox.showerror("Setup stopped", str(exc), parent=root)
            return
        install.config(state="disabled")
        text.set(
            "Installing client dependencies. This window stays responsive.\n\nDetails: "
            + str(Path(log_root) / "python_setup.log")
        )
        root.after(150, poll)

    def cancel():
        process = state["process"]
        if process is not None and process.poll() is None:
            messagebox.showinfo(
                "Setup running",
                "Wait for dependency installation to finish, then close the client if desired.",
                parent=root,
            )
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", cancel)
    buttons = tk.Frame(root)
    buttons.pack(side="bottom", fill="x", padx=20, pady=20)
    tk.Button(buttons, text="Cancel", command=cancel, width=18).pack(side="left")
    install = tk.Button(buttons, text="Install dependencies", command=start, width=24)
    install.pack(side="right")
    root.mainloop()
    if not state["success"]:
        raise SystemExit(0)
    importlib.invalidate_caches()
    if not dependencies_ready():
        raise RuntimeError(
            "The installed dependency versions could not be verified. See python_setup.log."
        )


def run(game, data, log_root):
    prepare_dependencies(log_root)

    sys._nfsmw_game_root = str(Path(game).resolve())
    sys._nfsmw_windowed_python = True
    sys._nfsmw_client_runtime = True
    sys._MEIPASS = str(Path(data).resolve())
    sys.frozen = True
    from NFSMW_Standalone import entrypoint

    entrypoint()
