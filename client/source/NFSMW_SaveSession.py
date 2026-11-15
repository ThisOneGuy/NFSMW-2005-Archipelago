from pathlib import Path
import hashlib
import json
import os
import tempfile
import configparser
import io
import logging


def preference_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 256 * 1024:
        return None
    try:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None
        encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read_string(text)
        return parser, after.st_mtime_ns
    except (OSError, ValueError, configparser.Error):
        return None


def copy_session_settings(base, session):
    folder = session / "NFS Most Wanted"
    target = folder / "Settings.ini"
    if not target.exists() and (folder / "settings.ini").exists():
        target = folder / "settings.ini"
    if any((folder / name).is_symlink() for name in ("Settings.ini", "settings.ini")):
        raise RuntimeError("Graphics settings must not be a link.")
    previous = preference_file(target)
    if target.exists() and not previous:
        return
    candidates = []
    for root in base.glob("session_v2_*"):
        manifest = root / "NFSMW_AP_Session.json"
        source_folder = root / "NFS Most Wanted"
        if (
            root.is_symlink()
            or source_folder.is_symlink()
            or manifest.is_symlink()
            or not manifest.is_file()
        ):
            continue
        try:
            identity = json.loads(manifest.read_text(encoding="utf-8"))
            if (
                not isinstance(identity, dict)
                or set(identity) != {"version", "server", "seed", "team", "slot"}
                or identity.get("version") != 2
                or identity_key(identity) != root.name
            ):
                continue
            for name in ("Settings.ini", "settings.ini"):
                parsed = preference_file(source_folder / name)
                if parsed:
                    candidates.append((parsed[1], str(source_folder / name), parsed[0]))
        except (OSError, ValueError):
            continue
    result = previous[0] if previous else configparser.ConfigParser(interpolation=None)
    result.optionxform = str
    original = {section: dict(result.items(section, raw=True)) for section in result.sections()}
    for _, _, settings in sorted(candidates, key=lambda entry: entry[:2]):
        for section in settings.sections():
            for key, value in settings.items(section, raw=True):
                lowered = key.casefold()
                if not lowered.startswith(
                    ("g_", "controller", "gamepad", "joystick", "keyboard", "binding")
                ):
                    continue
                destination = next(
                    (old for old in result.sections() if old.casefold() == section.casefold()),
                    section,
                )
                if not result.has_section(destination):
                    result.add_section(destination)
                equivalent = next(
                    (old for old in result[destination] if old.casefold() == lowered), key
                )
                if result.get(destination, equivalent, raw=True, fallback=None) != value:
                    result.set(destination, equivalent, value)
    if original == {
        section: dict(result.items(section, raw=True)) for section in result.sections()
    }:
        return
    folder.mkdir(parents=True, exist_ok=True)
    output = io.StringIO()
    result.write(output, space_around_delimiters=False)
    encoded = output.getvalue().encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix="settings_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_player_preferences(base, session):
    base, session = Path(base).absolute(), Path(session).absolute()
    for path in (base, session, session / "NFS Most Wanted", base / "preferences"):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError("Player preference folders must be normal directories.")
    if session.parent != base or not session.name.startswith("session_v2_"):
        raise RuntimeError("Player preferences require an isolated session folder.")
    shared = base / "preferences"
    shared.mkdir(exist_ok=True)
    destination = shared / "PlayerSettings.bin"
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise RuntimeError("Player preferences must be a normal file.")
    try:
        copy_session_settings(base, session)
    except OSError as exc:
        logging.getLogger("NFSMW").warning(
            "Could not carry over display settings: %s. Shared profile preferences remain enabled.",
            exc,
        )
    return destination


def identity_key(identity):
    return (
        "session_v2_"
        + hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
    )


def world_key(identity):
    return hashlib.sha256(
        json.dumps(
            [identity["seed"], identity["team"], identity["slot"]], ensure_ascii=True
        ).encode()
    ).hexdigest()


def native_profile(root, slot):
    root = Path(root)
    save = root / "NFS Most Wanted"
    paths = [save / slot, save / slot / slot]
    if save.is_symlink() or any(p.is_symlink() for p in paths):
        raise RuntimeError(f"Save path contains a link; files preserved: {root}")
    files = [p for p in paths if p.is_file()]
    if len(files) > 1:
        raise RuntimeError(f"Multiple native profiles in one session; files preserved: {root}")
    if not files:
        if paths[0].exists():
            raise RuntimeError(
                f"Existing slot folder has no complete profile; files preserved: {root}"
            )
        return None
    if not 0x4039 <= files[0].stat().st_size <= 1024 * 1024:
        raise RuntimeError(f"Existing profile is incomplete; files preserved: {files[0]}")
    return files[0]


def matching_sessions(base, identity):
    result = []
    base = Path(base).resolve()
    if not base.exists():
        return result
    for root in sorted(base.glob("session_v2_*")):
        manifest = root / "NFSMW_AP_Session.json"
        if (
            root.is_symlink()
            or not root.is_dir()
            or manifest.is_symlink()
            or not manifest.is_file()
        ):
            continue
        try:
            stored = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(stored, dict) or stored.get("version") != 2:
            continue
        if any(stored.get(k) != identity[k] for k in ("seed", "team", "slot")):
            continue
        if (
            set(stored) != {"version", "server", "seed", "team", "slot"}
            or identity_key(stored) != root.name
        ):
            raise RuntimeError(
                f"Existing session identity is inconsistent; files preserved: {root}"
            )
        profile = native_profile(root, identity["slot"])
        result.append((root, stored, profile))
    return result


def select_session(base, requested_key, identity):
    base = Path(base).resolve()
    sessions = matching_sessions(base, identity)
    binding = base / "NFSMW_AP_SaveBindings.json"
    if binding.is_symlink():
        raise RuntimeError("Save selection file must not be a link.")
    if binding.exists():
        try:
            selected = json.loads(binding.read_text(encoding="utf-8")).get(world_key(identity))
        except (ValueError, AttributeError) as exc:
            raise RuntimeError(
                "Save selections are unreadable; no new Career will be created."
            ) from exc
        if selected:
            for root, stored, profile in sessions:
                if root.name == selected and profile:
                    return root.name, stored, root
            raise RuntimeError(
                "The selected native save is missing; restore it before launching. No replacement Career created."
            )
    complete = [(r, i, p) for r, i, p in sessions if p]
    if len(complete) == 1:
        root, stored, _ = complete[0]
        return root.name, stored, root
    if len(complete) > 1:

        raise RuntimeError(
            "Multiple saves match this seed/team/slot. Resolve the duplicate saves before connecting. All copies are preserved; no new Career created."
        )

    def progressed(root):
        state = root / "NFSMW_AP_ClientState.json"
        if not state.exists():
            return False
        if state.is_symlink():
            raise RuntimeError("Client state must not be a link.")
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Not an object")
        except (ValueError, OSError) as exc:
            raise RuntimeError(
                "Existing client state is unreadable; no replacement Career created."
            ) from exc
        return any(
            data.get(k)
            for k in (
                "native_profile_seen",
                "delivered_received_indices",
                "won_race_locations",
                "defeated_blacklist_ranks",
                "queued_location_checks",
                "seen_locations",
            )
        )

    if any(progressed(root) for root, _, _ in sessions):
        raise RuntimeError(
            "Previous client progress exists but its native Career save is missing. Restore the save before launching; no replacement Career created."
        )
    return requested_key, identity, base / requested_key


def bind_session(base, identity, session):
    base = Path(base).resolve()
    if not any(r.name == session and p for r, _, p in matching_sessions(base, identity)):
        raise RuntimeError("Selection does not contain a complete save for this seed/team/slot.")
    path = base / "NFSMW_AP_SaveBindings.json"
    if path.is_symlink():
        raise RuntimeError("Save selection file must not be a link.")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(data, dict):
        raise RuntimeError("Existing save selections are unreadable.")
    data[world_key(identity)] = session
    fd, temp = tempfile.mkstemp(prefix="NFSMW_SaveBindings_", suffix=".tmp", dir=base)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def startup_has_profile(root, slot, previous_progress=False):
    found = native_profile(root, slot) is not None
    if not found and previous_progress:
        raise RuntimeError(
            "This computer recorded in-game progress, but this slot's native save is missing. "
            "Restore the save before launching; no replacement Career created."
        )
    return found
