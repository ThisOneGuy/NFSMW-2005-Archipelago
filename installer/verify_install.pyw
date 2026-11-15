from pathlib import Path, PurePosixPath
import hashlib
import json
import stat
import struct
import sys

CORE = (
    "NFSMWArchipelago.asi",
    "NFSMWArchipelago.tpk",
    "NFSMW_TurboTrap.wav",
    "NFSMW_FlashBangTrap.wav",
    "NFSMW_TruckTrap.wav",
)


def regular(path, root):
    current = path
    while True:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked installation paths are not supported: " + str(current))
        if current == root:
            return
        if current.parent == current:
            raise ValueError("Invalid installation path.")
        current = current.parent


def pe32(path):
    with path.open("rb") as stream:
        head = stream.read(64)
        if len(head) != 64 or head[:2] != b"MZ":
            return False
        offset = struct.unpack_from("<I", head, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 6:
            return False
        stream.seek(offset)
        return stream.read(6) == b"PE\0\0\x4c\x01"


def verify(root):
    root = Path(root).absolute()
    regular(root / "speed.exe", root)
    if not pe32(root / "speed.exe"):
        raise ValueError("Select the game folder containing the 32-bit speed.exe.")
    data = root / "NFSMWClient_Data"
    regular(data / "launcher_files.sha256", root)
    names = set()
    for line in (data / "launcher_files.sha256").read_text(encoding="utf-8").splitlines():
        if len(line) < 67 or line[64:66] != " *":
            raise ValueError("Invalid client file list.")
        name = line[66:]
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or ":" in name
            or "\\" in name
            or name in names
        ):
            raise ValueError("Invalid client file path.")
        path = data / relative
        regular(path, root)
        if hashlib.sha256(path.read_bytes()).hexdigest() != line[:64]:
            raise ValueError("A client file is missing or damaged: " + name)
        names.add(name)
    if not {
        "boot.pyw",
        "runtime/pythonw.exe",
        "app.zip",
        "bundle.json",
        "verify_install.pyw",
    }.issubset(names):
        raise ValueError("The client file list is incomplete.")
    manifest = json.loads((data / "bundle.json").read_text(encoding="utf-8"))
    for name in CORE:
        path = root / "scripts" / name
        regular(path, root)
        expected = manifest["core_files"][name]
        if (
            path.stat().st_size != expected["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]
        ):
            raise ValueError("Install the updated required game scripts: " + name)
    if not pe32(root / "scripts/NFSMWArchipelago.asi"):
        raise ValueError("The game plugin must be a 32-bit Windows plugin.")


def main():
    if len(sys.argv) != 2:
        return 2
    root = Path(sys.argv[1]).absolute()
    try:
        verify(root)
        result = {"ok": True}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    try:
        report = root / "NFSMWClient_Data/install_status.json"
        regular(report.parent, root)
        if report.exists():
            regular(report, root)
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        return 1
    return int(not result["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
