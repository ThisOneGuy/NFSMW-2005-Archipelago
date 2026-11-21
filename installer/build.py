from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from framework_build import framework_flags
from payload_files import ignored_data_files, sanitize_runtime_archives
from package_release import allowed

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(args):
    out = args.destination.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use an empty build directory.")
    subprocess.run([sys.executable, str(SOURCE / "client/tools/build.py")], check=True)
    payload = out / "payload"
    data = payload / "NFSMWClient_Data"
    payload.mkdir(parents=True)
    shutil.copytree(args.runtime_data, data, ignore=ignored_data_files(args.runtime_data))
    sanitize_runtime_archives(data)
    for name in ("boot.pyw", "remove_retired.pyw", "verify_install.pyw"):
        shutil.copy2(HERE / name, data / name)
    shutil.copy2(SOURCE / "client/NFSMWClient.pyw", payload / "NFSMWClient.pyw")
    shutil.copy2(SOURCE / "client/NFSMWClient_Data/app.zip", data / "app.zip")
    shutil.copytree(SOURCE / "client/NFSMWClient_Data/assets", data / "assets", dirs_exist_ok=True)
    shutil.copytree(
        SOURCE / "client/NFSMWClient_Data/licenses", data / "licenses", dirs_exist_ok=True
    )
    previous_license = data / "licenses/Archipelago-LICENSE.txt"
    current_license = data / "licenses/LICENSE-Archipelago.txt"
    if (
        previous_license.is_file()
        and previous_license.read_bytes() == current_license.read_bytes()
    ):
        previous_license.unlink()
    shutil.copy2(HERE / "archipelago.ico", data / "assets/archipelago.ico")
    (data / "launcher").mkdir(exist_ok=True)
    shutil.copy2(SOURCE / "world/nfsmw.apworld", data / "launcher/nfsmw.apworld")
    for path in sorted(data.rglob("*"), reverse=True):
        if path.is_file() and not allowed(path.relative_to(data)):
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    compiler = [str(args.csc.resolve())]
    if args.mono:
        compiler = (
            [str(args.mono.resolve())]
            + (["--config", str(args.mono_config.resolve())] if args.mono_config else [])
            + compiler
        )
    subprocess.run(
        compiler
        + framework_flags(
            args.framework_reference, ("System.Windows.Forms.dll", "System.Drawing.dll")
        )
        + [
            "-target:winexe",
            "-optimize+",
            "-win32icon:" + str(HERE / "archipelago.ico"),
            "-out:" + str(payload / "client.exe"),
            str(HERE / "Client.cs"),
        ],
        check=True,
    )
    files = {
        p.relative_to(data).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(data.rglob("*"))
        if p.is_file() and p.name not in ("bundle.json", "launcher_files.sha256")
    }
    manifest = {
        "format": 1,
        "client_build": "1.0.6",
        "native_build": "1.0.6",
        "mode": "official-pythonw-process",
        "runtime": "CPython 3.13.17 x64",
        "entrypoint": "client.exe",
        "distribution": "side-by-side",
        "executable_sha256": digest(payload / "client.exe"),
        "files": files,
        "core_files": {
            p.name: {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in args.core_scripts.iterdir()
            if p.name
            in (
                "NFSMWArchipelago.asi",
                "NFSMWArchipelago.tpk",
                "NFSMW_TurboTrap.wav",
                "NFSMW_FlashBangTrap.wav",
                "NFSMW_TruckTrap.wav",
            )
        },
    }
    (data / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (data / "launcher_files.sha256").write_text(
        "".join(
            digest(p) + " *" + p.relative_to(data).as_posix() + "\n"
            for p in sorted(data.rglob("*"))
            if p.is_file() and p.name != "launcher_files.sha256"
        )
    )
    flag = "/D" if os.name == "nt" else "-D"
    subprocess.run(
        [
            str(args.makensis.resolve()),
            flag + "OUTPUT=" + str(out),
            flag + "ICON=" + str(HERE / "archipelago.ico"),
            flag + "PAYLOAD=" + str(payload),
            flag + "CORE=" + str(args.core_scripts.resolve()),
            str(HERE / "Setup.nsi"),
        ],
        check=True,
    )
    print(out / "NFSMW_Setup.exe")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in (
        "runtime-data",
        "core-scripts",
        "destination",
        "csc",
        "framework-reference",
        "makensis",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--mono", type=Path)
    parser.add_argument("--mono-config", type=Path)
    build(parser.parse_args())
