from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path
import sys


def configure_gui(data):
    if sys.platform == "win32":
        os.environ["TCL_LIBRARY"] = str(data / "runtime/tcl/tcl8.6")
        os.environ["TK_LIBRARY"] = str(data / "runtime/tcl/tk8.6")


def configure_protocol(data):

    sys._nfsmw_client_runtime = True
    import settings

    settings.skip_autosave = True
    settings.get_settings._cache = settings.Settings(None)
    import Utils

    user = data / "user"
    user.mkdir(parents=True, exist_ok=True)
    Utils.local_path.cached_path = str(data)
    Utils.user_path.cached_path = str(user)
    Utils.home_path.cached_path = str(user)
    Utils.cache_path.cached_path = str(user / "cache")


def entrypoint():
    from NFSMW_Desktop import (
        desktop_state_directory,
        WindowedStream,
        DesktopSession,
        run_desktop,
        show_error,
    )

    directory = desktop_state_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stream = None
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            if stream is None:
                stream = WindowedStream(directory / "desktop.log")
            setattr(sys, name, stream)
    if sys.stdin is None:
        sys.stdin = open(os.devnull, encoding="utf-8")
    game = Path(getattr(sys, "_nfsmw_game_root", Path(sys.executable).resolve().parent)).resolve()
    data = Path(sys._MEIPASS)
    try:
        windowed_python = bool(getattr(sys, "_nfsmw_windowed_python", False))
        if not windowed_python:
            configure_gui(data)

        if asyncio.run(DesktopSession().notify()):
            return
        from NFSMW_DesktopInstall import ensure_configuration

        if windowed_python and not (game / "speed.exe").is_file():
            raise RuntimeError(
                "Place NFSMWClient.pyw and NFSMWClient_Data beside the game's speed.exe, then open NFSMWClient.pyw again."
            )
        if not (game / "speed.exe").is_file():
            raise RuntimeError("Install the connection client beside speed.exe using NFSMW Setup.")
        ensure_configuration(
            game,
            data,
            entry_name=getattr(
                sys, "_nfsmw_entry_name", "NFSMWClient.pyw" if windowed_python else "client.exe"
            ),
        )
        configure_protocol(data)
        asyncio.run(run_desktop())
    except (Exception, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            return
        logging.getLogger("NFSMW").exception("Standalone startup failed")
        show_error(
            f'Could not open the NFSMW client: {exc}\n\nDetails: {directory / "desktop.log"}'
        )
        raise SystemExit(1) from None
