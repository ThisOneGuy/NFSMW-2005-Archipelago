from __future__ import annotations
import asyncio
from contextlib import suppress
import hmac
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile

BUILD = "1.0.6"
HERE = Path(__file__).resolve().parent
CONTROL_HOST, CONTROL_PORT = "127.0.0.1", 38284


def loaded_payload_hash():
    data = getattr(sys, "_MEIPASS", None)
    archive = Path(data) / "app.zip" if data else None
    if archive is not None and archive.is_file():
        return hashlib.sha256(archive.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for path in sorted(HERE.glob("*.py")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


LOADED_PAYLOAD_HASH = loaded_payload_hash()


def desktop_state_directory():
    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
        / "NFSMWArchipelago"
    )


class DesktopSession:
    def __init__(self, path=None, port=CONTROL_PORT):
        self.path = Path(path) if path else desktop_state_directory() / "desktop_session.json"
        self.port = port
        self.token = secrets.token_hex(32)
        self.server = None
        self.context = None
        self.pending_show = False
        self.view_log = None
        self.view_id = secrets.token_hex(12)
        self.payload_hash = LOADED_PAYLOAD_HASH
        self.game_root = str(
            Path(getattr(sys, "_nfsmw_game_root", Path(sys.executable).resolve().parent)).resolve()
        )

    def update_required_message(self):
        return (
            "Another NFSMW connection client is still running. Close its connection screen "
            "and exit that client, then reopen client.exe from the updated game folder:\n"
            + self.game_root
        )

    async def notify(self):
        writer = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            port, token = data["port"], data["token"]
            if (
                not isinstance(port, int)
                or not 0 < port < 65536
                or not isinstance(token, str)
                or len(token) != 64
            ):
                return False
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(CONTROL_HOST, port, limit=1024), 1.0
            )
            writer.write(
                (
                    json.dumps(
                        {
                            "action": "show",
                            "token": token,
                            "payload_hash": self.payload_hash,
                            "game_root": self.game_root,
                        }
                    )
                    + "\n"
                ).encode()
            )
            await writer.drain()
            response = json.loads(await asyncio.wait_for(reader.readline(), 1.0))
            if not isinstance(response, dict):
                return False
            if response.get("client_mismatch") is True:
                raise RuntimeError(self.update_required_message())
            if response.get("ok") is not True:
                return False
            if (
                response.get("payload_hash") != self.payload_hash
                or response.get("game_root") != self.game_root
            ):
                raise RuntimeError(self.update_required_message())
            return True
        except (OSError, ValueError, KeyError, TypeError, asyncio.TimeoutError):
            return False
        finally:
            if writer is not None:
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()

    async def acquire(self):

        if await self.notify():
            return False
        try:
            self.server = await asyncio.start_server(
                self.handle, CONTROL_HOST, self.port, limit=8192
            )
        except OSError as exc:
            for _ in range(20):
                if await self.notify():
                    return False
                await asyncio.sleep(0.1)
            raise RuntimeError(
                "The NFSMW client is already starting, or another program is using its connection port."
            ) from exc
        self.port = self.server.sockets[0].getsockname()[1]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".nfsmw-session-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(
                    {
                        "port": self.port,
                        "token": self.token,
                        "pid": os.getpid(),
                        "build": BUILD,
                        "executable": sys.executable,
                        "payload_hash": self.payload_hash,
                        "game_root": self.game_root,
                    },
                    out,
                )
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True

    async def handle(self, reader, writer):
        allowed = False
        try:
            raw = await asyncio.wait_for(reader.readline(), 1.0)
            request = json.loads(raw)
            allowed = (
                isinstance(request, dict)
                and isinstance(request.get("token"), str)
                and hmac.compare_digest(request["token"], self.token)
            )
            response = {"ok": False}
            if allowed and request.get("action") == "show":
                if (
                    request.get("payload_hash") != self.payload_hash
                    or request.get("game_root") != self.game_root
                ):
                    response = {"ok": False, "client_mismatch": True}
                else:
                    if self.context is not None:
                        self.focus()
                    else:
                        self.pending_show = True
                    response = {
                        "ok": True,
                        "payload_hash": self.payload_hash,
                        "game_root": self.game_root,
                    }
            elif allowed and self.context is not None and request.get("action") == "snapshot":
                from NFSMW_ClientView import snapshot

                response = {
                    "ok": True,
                    "snapshot": snapshot(self.context, self.view_log, self.view_id),
                }
            elif (
                allowed and self.context is not None and request.get("action") == "connection_link"
            ):
                screen = getattr(self.context, "connection_screen", None)
                if screen is None:
                    response = {"ok": False, "error": "The connection screen is not ready yet."}
                else:
                    try:
                        response = screen.accept_connection_link(request.get("connection"))
                    except ValueError as exc:
                        response = {"ok": False, "error": str(exc)}
                response["operation"] = "connection_link"
            elif (
                allowed
                and self.context is not None
                and request.get("action") in ("command", "hint_status", "reveal", "hint_request", "garage_resend")
            ):
                from NFSMW_ClientView import perform_action

                response = await perform_action(self.context, request)
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        except (OSError, ValueError, TypeError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    def attach(self, context):
        self.context = context
        from NFSMW_ClientView import ViewLog

        self.view_log = ViewLog()
        self.view_log.install()
        if self.pending_show:
            self.pending_show = False
            self.focus()

    def focus(self):

        screen = getattr(self.context, "connection_screen", None)
        if screen is not None and not screen.closed:
            screen.root.deiconify()
            screen.root.lift()
            screen.root.focus_force()

    async def close(self):
        if self.view_log is not None:
            self.view_log.uninstall()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("token") == self.token:
                self.path.unlink()
        except (OSError, ValueError, TypeError):
            pass


class AttachedGame:
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x00101000, False, pid)
        if not self.handle:
            raise OSError("Could not track the running game.")

    def poll(self):
        import ctypes
        from ctypes import wintypes

        if self.kernel.WaitForSingleObject(self.handle, 0) == 258:
            return None
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError("Could not read the game's exit code.")
        return code.value

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


async def watch_game_exit(ctx, interval=0.25):
    tracked = None
    attached = None
    try:
        while not ctx.exit_event.is_set():

            tracked = getattr(ctx, "desktop_game_process", None) or tracked
            current = getattr(ctx, "game_process", None)
            ready = getattr(ctx, "game_ready_pids", set())
            if (
                tracked is None
                and current is not None
                and current.poll() is None
                and (getattr(current, "pid", None) in ready or (sys.platform != "win32" and ready))
            ):
                tracked = current
            if tracked is None and sys.platform == "win32" and ctx.game_ready_pids:
                try:
                    attached = AttachedGame(next(iter(ctx.game_ready_pids)))
                    tracked = attached
                except OSError:
                    pass
            code = tracked.poll() if tracked is not None else None
            if code is not None:
                if code:
                    logging.getLogger("NFSMW").error(
                        "speed.exe exited with code %s (0x%08X). Check NFSMWArchipelago-crash.log and .dmp in the game folder.",
                        code,
                        code & 0xFFFFFFFF,
                    )
                try:
                    ctx.sync_slot_save()
                except (OSError, ValueError):
                    logging.getLogger("NFSMW").exception("Final save synchronization failed")
                logging.getLogger("NFSMW").info(
                    "NFSMW closed. Disconnecting the client from Archipelago."
                )
                ctx.exit_event.set()
                return
            await asyncio.sleep(interval)
    finally:
        if attached is not None:
            attached.close()
        elif isinstance(tracked, AttachedGame):
            tracked.close()


async def run_desktop():
    session = DesktopSession()
    if not await session.acquire():
        return
    try:

        import argparse
        import NFSMW_AP_Client as client

        args = argparse.Namespace(
            ap_text_window=False,
            connection_screen_only=False,
            nogui=False,
            desktop=True,
            desktop_session=session,
            name=None,
            password=None,
            connect=None,
        )
        await client.main(args)
    finally:
        await session.close()


def show_error(message):
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(message), "NFSMW Archipelago Client", 0x10)
    else:
        print(message, file=sys.stderr)


class WindowedStream:
    encoding = "utf-8"

    def __init__(self, path):
        from logging.handlers import RotatingFileHandler

        self.handler = RotatingFileHandler(
            path, maxBytes=1024 * 1024, backupCount=1, encoding="utf-8"
        )
        self.writing = False

    def write(self, text):
        if text and not self.writing:
            self.writing = True
            try:
                self.handler.handle(
                    logging.LogRecord("desktop", logging.INFO, "", 0, text.rstrip("\n"), (), None)
                )
            except (OSError, ValueError):
                pass
            finally:
                self.writing = False
        return len(text)

    def flush(self):
        self.handler.flush()

    def isatty(self):
        return False

    def fileno(self):
        return self.handler.stream.fileno()
