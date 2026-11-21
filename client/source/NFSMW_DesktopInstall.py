from __future__ import annotations
import configparser
import io
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile

BUILD = "1.0.6"
CONFIG = "NFSMW_AP_Client.ini"


def atomic_write(target, content):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.read_bytes() == content:
        return
    fd, temp = tempfile.mkstemp(prefix=".nfsmw-install-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def atomic_copy(source, target):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        return
    atomic_write(target, source.read_bytes())


def ensure_configuration(game, data, previous=None, entry_name="client.exe"):
    game, data = Path(game), Path(data)
    target = game / CONFIG
    previous = Path(previous) if previous else None
    source = (
        target
        if target.is_file()
        else previous if previous and previous.is_file() else data / "assets/default.ini"
    )
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(source, encoding="utf-8-sig")
    from NFSMW_RetiredFeatures import remove_retired_settings

    remove_retired_settings(cfg)
    if not cfg.has_section("Launcher"):
        cfg.add_section("Launcher")
    cfg.set("Launcher", "GameExe", str((game / "speed.exe").resolve()))

    save = cfg.get("Launcher", "SaveRoot", fallback="")
    expanded = Path(os.path.expandvars(save)).expanduser() if save else None
    if (
        expanded is not None
        and not expanded.is_absolute()
        and not PureWindowsPath(save).is_absolute()
        and "%" not in save
    ):
        cfg.set("Launcher", "SaveRoot", str((source.parent / expanded).resolve()))
    if cfg.has_section("Runtime"):
        for option in ("PythonExecutable", "ArchipelagoRoot"):
            cfg.remove_option("Runtime", option)
        if not cfg.items("Runtime"):
            cfg.remove_section("Runtime")
    out = io.StringIO()
    cfg.write(out)
    atomic_write(target, out.getvalue().encode("utf-8"))
    if source != target:
        for name in ("NFSMW_AP_ClientState.json", "NFSMW_AP_ShopCache.json"):
            old = source.parent / name
            new = game / name
            if old.is_file() and not new.exists():
                atomic_copy(old, new)

    from NFSMW_Desktop import desktop_state_directory

    registration = desktop_state_directory() / "client_install.json"
    atomic_write(
        registration,
        (
            json.dumps(
                {"format": 1, "build": BUILD, "executable": str((game / entry_name).resolve())},
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8"),
    )
    return target
