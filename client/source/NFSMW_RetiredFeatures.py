from pathlib import Path
import os
import re
import stat
import struct


RETIRED_TRAP_ID = 1950006
DISABLED_ENVIRONMENT = (
    "NFSMW_AP_DEALERSHIP_UMA_TEST",
    "NFSMW_AP_UMA_TEST_TIMER",
    "NFSMW_AP_UMA_TRAP",
    "NFSMW_AP_UMA_RACERS_READY",
    "NFSMW_AP_UMA_POLICE_READY",
    "NFSMW_AP_CHARACTER_PACK_READY",
    "NFSMW_AP_FENOMENO_ARREST_READY",
)
REMOVED_TREES = (
    "scripts/NFSMW_Remixed",
    "scripts/NFSMW_UmaFootsteps",
    "scripts/NFSMW_Characters",
    "NFSMWClient_Data/runtime/tcl/nmake",
)
REMOVED_FILES = (
    "scripts/NFSMWArchipelago.asi.previous",
    "scripts/NFSMWArchipelago.asi.bak",
    "scripts/NFSMWArchipelago.asi.old",
    "NFSMW_Character.py",
    "client/NFSMW_Character.py",
    "scripts/NFSMW_UmaMusumeTrap.wav",
    "scripts/NFSMW_UmaMusumeTrap_Source.mp3",
    "scripts/NFSMW_UmaFootstep.wav",
    "NFSMWClient_Data/licenses/BUNDLE_SOURCES.json",
    "NFSMWClient_Data/licenses/SOURCES.json",
    "NFSMWClient_Data/assets/NFSMW_RaceMap_Status.csv",
    "NFSMWClient_Data/runtime/tcl/tclConfig.sh",
    "NFSMWClient_Data/runtime/tcl/tclooConfig.sh",
    "NFSMWClient_Data/runtime/tcl/tcl8/8.5/tcltest-2.5.8.tm",
    "NFSMWClient_Data/site-packages/certifi/py.typed",
    "NFSMWClient_Data/site-packages/jellyfish/py.typed",
    "NFSMWClient_Data/site-packages/orjson/py.typed",
    "NFSMWClient_Data/site-packages/pathspec/py.typed",
    "NFSMWClient_Data/site-packages/platformdirs/py.typed",
    "NFSMWClient_Data/site-packages/schema/py.typed",
    "NFSMWClient_Data/site-packages/websockets/py.typed",
    "NFSMWClient_Data/site-packages/websockets/speedups.c",
)


def disabled_environment(environment):
    environment = dict(environment)
    for key in tuple(environment):
        if (
            key.startswith(("NFSMW_AP_UMA_", "NFSMW_AP_FENOMENO_"))
            or key == "NFSMW_AP_DEALERSHIP_UMA_TEST"
        ):
            del environment[key]
    environment.update(dict.fromkeys(DISABLED_ENVIRONMENT, "0"))
    environment["NFSMW_AP_PLAYER_CHARACTER"] = "original"
    return environment


def retired_item_payload(payload, enabled, pending):
    payload = dict(payload)
    if payload.get("item_id") == RETIRED_TRAP_ID:
        payload.update(item_type="retired", trap_trigger=False, notify=False)
    elif payload.get("item_type") == "trap":
        payload["trap_trigger"] = bool(enabled and pending)
    return payload


def remove_retired_settings(configuration):
    if configuration.has_section("Testing"):
        for key in ("UmaTrapRepeatTimer", "UmaTrapFirstDelaySeconds", "UmaTrapRepeatDelaySeconds"):
            configuration.remove_option("Testing", key)
        if not configuration.items("Testing"):
            configuration.remove_section("Testing")


def _linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _validate_game(game):
    if not game.is_dir() or _linked(game):
        raise ValueError("Select the actual game folder containing speed.exe.")
    executable = game / "speed.exe"
    if _linked(executable):
        raise ValueError("The game executable must be a normal file.")
    with executable.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("The selected folder does not contain a 32-bit game executable.")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset < 64 or offset > executable.stat().st_size - 6:
            raise ValueError("Invalid game executable.")
        stream.seek(offset)
        if stream.read(6) != b"PE\0\0\x4c\x01":
            raise ValueError("The selected game executable is not 32-bit.")


def cleanup_retired_assets(game_directory):
    game = Path(os.path.abspath(game_directory))
    _validate_game(game)
    result = {"removed_files": 0, "freed_bytes": 0, "errors": [], "skipped_links": []}

    def record_error(path, exc):
        result["errors"].append({"path": path.relative_to(game).as_posix(), "error": str(exc)})

    def permitted(path):
        current = game
        for part in path.relative_to(game).parts:
            current = current / part
            try:
                if _linked(current):
                    result["skipped_links"].append(current.relative_to(game).as_posix())
                    return False
            except FileNotFoundError:
                return False
            except OSError as exc:
                record_error(current, exc)
                return False
        return True

    def remove_file(path):
        if not permitted(path):
            return
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                return
            path.unlink()
            result["removed_files"] += 1
            result["freed_bytes"] += info.st_size
        except OSError as exc:
            record_error(path, exc)

    def remove_tree(path):
        if not permitted(path) or not path.is_dir():
            return
        try:
            for child in path.iterdir():
                if not permitted(child):
                    continue
                if child.is_dir():
                    remove_tree(child)
                else:
                    remove_file(child)
            if not any(path.iterdir()):
                path.rmdir()
        except OSError as exc:
            record_error(path, exc)

    canonical = game / "scripts/NFSMWArchipelago.asi"
    for parent in (game, game / "scripts", game / "plugins"):
        if not parent.is_dir():
            continue
        if _linked(parent):
            result["skipped_links"].append(parent.relative_to(game).as_posix())
            continue
        for plugin in parent.iterdir():
            if plugin.suffix.casefold() not in (".asi", ".dll") or not permitted(plugin):
                continue
            try:
                raw = plugin.read_bytes()
                owned = b"NFSMW_AP_" in raw and (
                    b"NFSMWArchipelago" in raw or plugin.name.casefold().startswith("nfsmw")
                )
                compatible = (
                    b"NFSMW_AP_RUNTIME_ABI_V1" in raw and b"NFSMW_AP_RELEASE_OPTIONS_V1" in raw
                )
                if owned and (plugin != canonical or not compatible):
                    remove_file(plugin)
            except OSError as exc:
                record_error(plugin, exc)

    for relative in REMOVED_TREES:
        remove_tree(game / relative)
    for relative in REMOVED_FILES:
        path = game / relative
        remove_file(path)
        if not permitted(path.parent) or not path.parent.is_dir():
            continue
        try:
            for candidate in path.parent.iterdir():
                if re.fullmatch(
                    r"\.?" + re.escape(path.name) + r"\.[A-Za-z0-9._-]+", candidate.name
                ):
                    remove_file(candidate)
        except OSError as exc:
            record_error(path.parent, exc)
    for scripts in (game, game / "scripts", game / "plugins"):
        if not permitted(scripts) or not scripts.is_dir():
            continue
        try:
            for candidate in scripts.iterdir():
                if candidate.suffix.casefold() not in (".asi", ".dll"):
                    continue
                if (
                    not permitted(candidate)
                    or not candidate.is_file()
                    or candidate.stat().st_size > 32 * 1024 * 1024
                ):
                    continue
                data = candidate.read_bytes()
                police = any(
                    marker in data
                    for marker in (
                        b"NFSMW_AP_UMA_POLICE_",
                        b"NFSMW_AP_FENOMENO_ARREST_",
                        b"AP UMA POLICE: Fenomeno",
                    )
                )
                retired = b"NFSMW_AP_CONNECTION_UI_" in data and any(
                    marker in data
                    for marker in (
                        b"NFSMW_AP_UMA_TRAP_",
                        b"NFSMW_AP_PLAYER_CHARACTER_",
                        b"NFSMW_AP_REMIX_SOUNDTRACK_",
                    )
                )
                if data.startswith(b"MZ") and (police or retired):
                    remove_file(candidate)
        except OSError as exc:
            record_error(scripts, exc)
    result["skipped_links"] = sorted(set(result["skipped_links"]))
    return result
