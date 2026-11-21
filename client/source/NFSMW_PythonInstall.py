from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from NFSMW_RetiredFeatures import cleanup_retired_assets, _validate_game, _linked


CORE = (
    "NFSMWArchipelago.asi",
    "NFSMWArchipelago.tpk",
    "NFSMW_TurboTrap.wav",
    "NFSMW_FlashBangTrap.wav",
    "NFSMW_TruckTrap.wav",
)


def _safe_file(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Invalid installation file path.")
    path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _linked(current):
                raise ValueError("Linked installation paths are not supported: " + name)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Installation path leaves its folder.")
    return path


def _verify(path, expected):
    raw = path.read_bytes()
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("A package file is missing or damaged: " + path.name)


def _replace(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".nfsmw-install-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            with source.open("rb") as incoming:
                shutil.copyfileobj(incoming, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def game_folder(value):
    text = os.fspath(value).strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    if not text:
        raise ValueError("Choose the game folder containing speed.exe.")
    game = Path(os.path.abspath(text))
    if game.is_file():
        if game.name.casefold() != "speed.exe":
            raise ValueError("Choose the game folder or speed.exe.")
        game = game.parent
    return game


def install(source_directory, game_directory, install_scripts=True):
    source = Path(source_directory).resolve()
    game = game_folder(game_directory)
    _validate_game(game)
    if source == game:
        raise ValueError("Extract the update to a separate folder before installing it.")
    data = source / "NFSMWClient_Data"
    manifest = json.loads((data / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("mode") != "pythonw" or manifest.get("entrypoint") != "NFSMWClient.pyw":
        raise ValueError("Extract the complete Python package before installing.")
    client = _safe_file(source, "NFSMWClient.pyw")
    if hashlib.sha256(client.read_bytes()).hexdigest() != manifest["entrypoint_sha256"]:
        raise ValueError("The Python client is missing or damaged.")
    staged = []
    for name, expected in manifest["files"].items():
        file = _safe_file(data, name)
        _verify(file, expected)
        staged.append((file, _safe_file(game, "NFSMWClient_Data/" + name)))
    scripts = []
    native = manifest["native_build"].encode("ascii")
    if install_scripts:
        if set(manifest.get("core_files", {})) != set(CORE):
            raise ValueError("The package is missing required scripts.")
        for name in CORE:
            file = _safe_file(source, "scripts/" + name)
            _verify(file, manifest["core_files"][name])
            scripts.append((file, _safe_file(game, "scripts/" + name)))
        plugin = (source / "scripts/NFSMWArchipelago.asi").read_bytes()
    else:
        plugin = _safe_file(game, "scripts/NFSMWArchipelago.asi").read_bytes()
    if (
        not plugin.startswith(b"MZ")
        or native not in plugin
        or b"NFSMW_AP_BOUNTY_REQUIREMENTS_V1" not in plugin
        or b"NFSMW_AP_RUNTIME_ABI_V1" not in plugin
        or b"NFSMW_AP_RELEASE_OPTIONS_V1" not in plugin
        or b"NFSMW_AP_BOUNTY_EARNINGS_V2" not in plugin
        or b"NFSMW_AP_SAVE_BOOT_FLOW_V5" not in plugin
        or b"NFSMW_AP_RANDOMIZED_CAREER_V4" not in plugin
        or b"NFSMW_AP_SHARED_PREFERENCES_V1" not in plugin
        or b"NFSMW_AP_SPAWN_HOOK_V2" not in plugin
        or b"NFSMW_AP_CRASH_REPORT_V2" not in plugin
        or b"NFSMW_AP_GOALS_V1" not in plugin
        or b"NFSMW_AP_FINAL_ESCAPE_V2" not in plugin
        or b"NFSMW_AP_OPTIONAL_SHOPS_V1" not in plugin
    ):
        raise ValueError("Install the current required game scripts to use this update.")
    _safe_file(game, "NFSMWClient.pyw")
    _safe_file(game, "NFSMWClient_Data/bundle.json")
    cleanup = cleanup_retired_assets(game)
    if cleanup["errors"] or cleanup["skipped_links"]:
        raise OSError(
            "Some old mod files could not be removed. Close the game and client, then try again."
        )
    for file, target in scripts + staged:
        _replace(file, target)
    _replace(client, game / "NFSMWClient.pyw")
    _replace(data / "bundle.json", game / "NFSMWClient_Data/bundle.json")
    return {"game": str(game), "client_build": manifest["client_build"], "cleanup": cleanup}


def launch_client(game_directory):
    game = Path(game_directory)
    pythonw = (
        Path(sys.executable).with_name("pythonw.exe") if os.name == "nt" else Path(sys.executable)
    )
    if not pythonw.is_file():
        raise RuntimeError("Use Python with Tcl/Tk; Windows also requires pythonw.exe.")
    return subprocess.Popen(
        [str(pythonw), str(game / "NFSMWClient.pyw")],
        cwd=game,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main(source_directory):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("NFSMW Client Setup")
    root.geometry("670x330")
    root.resizable(False, False)
    folder = tk.StringVar()
    scripts = tk.BooleanVar(value=True)
    launch = tk.BooleanVar(value=True)
    tk.Label(
        root, text="Choose the game folder containing speed.exe.", anchor="w", padx=18, pady=16
    ).pack(fill="x")
    row = tk.Frame(root)
    row.pack(fill="x", padx=18)
    tk.Entry(row, textvariable=folder).pack(side="left", fill="x", expand=True)

    def browse():
        selected = filedialog.askdirectory(parent=root, title="Choose the NFSMW game folder")
        if selected:
            folder.set(str(game_folder(selected)))

    tk.Button(row, text="Browse", command=browse, width=12).pack(side="right", padx=(8, 0))
    tk.Checkbutton(root, text="Install required game scripts", variable=scripts).pack(
        anchor="w", padx=18, pady=(18, 0)
    )
    tk.Checkbutton(root, text="Launch NFSMW Client when finished", variable=launch).pack(
        anchor="w", padx=18
    )
    notice = tk.StringVar(
        value="Close the game and connection client before installing.\n64-bit Python 3.11–3.13 with pip and Tcl/Tk is required."
    )
    tk.Label(root, textvariable=notice, justify="left", wraplength=625, padx=18, pady=12).pack(
        fill="x"
    )

    def start():
        if not folder.get().strip():
            messagebox.showerror(
                "Game folder required", "Choose the folder containing speed.exe.", parent=root
            )
            return
        install_button.config(state="disabled")
        notice.set("Installing the client and game scripts...")
        root.update_idletasks()
        try:
            result = install(source_directory, folder.get().strip(), scripts.get())
            notice.set(
                "Installed "
                + result["client_build"]
                + ". Install the included nfsmw.apworld and restart Archipelago Launcher."
            )
            if launch.get():
                launch_client(result["game"])
            install_button.config(text="Installed")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            messagebox.showerror("Installation stopped", str(exc), parent=root)
            install_button.config(state="normal")

    install_button = tk.Button(root, text="Install", command=start, width=20)
    install_button.pack(side="right", padx=18, pady=12)
    tk.Button(root, text="Close", command=root.destroy, width=14).pack(
        side="left", padx=18, pady=12
    )
    root.mainloop()
