from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CORE = (
    "NFSMWArchipelago.asi",
    "NFSMWArchipelago.tpk",
    "NFSMW_TurboTrap.wav",
    "NFSMW_FlashBangTrap.wav",
    "NFSMW_TruckTrap.wav",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(destination, core_scripts=None):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Use an empty Python package directory.")
    if (
        not (ROOT / "NFSMWClient_Data/app.zip").is_file()
        or not (ROOT.parent / "world/nfsmw.apworld").is_file()
    ):
        subprocess.run([sys.executable, str(ROOT / "tools/build.py")], check=True)
    data = destination / "NFSMWClient_Data"
    data.mkdir(parents=True)
    for name in ("NFSMWClient.pyw", "NFSMW_Install.pyw"):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copy2(ROOT.parent / "NFSMW.yaml", destination / "NFSMW.yaml")
    source = ROOT / "NFSMWClient_Data"
    shutil.copy2(source / "app.zip", data / "app.zip")
    shutil.copytree(source / "assets", data / "assets")
    licenses = data / "licenses"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE-Archipelago.txt", licenses / "LICENSE-Archipelago.txt")
    for p in (source / "licenses").iterdir():
        if p.is_file() and p.name.upper().startswith(
            ("LICENSE", "COPYING", "NOTICE", "PYTHON-NOTICES")
        ):
            shutil.copy2(p, licenses / p.name)
    (data / "launcher").mkdir()
    shutil.copy2(ROOT.parent / "world/nfsmw.apworld", data / "launcher/nfsmw.apworld")
    files = {
        p.relative_to(data).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in data.rglob("*")
        if p.is_file()
    }
    manifest = {
        "format": 1,
        "client_build": "1.0.5",
        "native_build": "1.0.5",
        "mode": "pythonw",
        "files": files,
        "entrypoint": "NFSMWClient.pyw",
        "entrypoint_sha256": digest(destination / "NFSMWClient.pyw"),
    }
    if core_scripts:
        scripts = destination / "scripts"
        scripts.mkdir()
        for name in CORE:
            shutil.copy2(Path(core_scripts) / name, scripts / name)
        manifest["core_files"] = {
            name: {"bytes": (scripts / name).stat().st_size, "sha256": digest(scripts / name)}
            for name in CORE
        }
    (data / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--core-scripts", type=Path)
    args = parser.parse_args()
    print(stage(args.destination, args.core_scripts))
