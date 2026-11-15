from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from payload_files import unnecessary_document, runtime_development_file

SOURCE = Path(__file__).resolve().parent.parent
EXCLUDED = {"__pycache__", ".git", "user", "build", "dist", "objects", "qa", "tests"}
GENERATED_SOURCE_FILES = {
    "world/nfsmw.apworld",
    "client/NFSMWClient_Data/app.zip",
    "client/NFSMWClient_Data/bundle.json",
    "client/NFSMWClient_Data/launcher/nfsmw.apworld",
}


def allowed(path):
    return (
        not EXCLUDED.intersection(path.parts)
        and not path.name.casefold().startswith("readme")
        and not unnecessary_document(path)
        and not runtime_development_file(path)
        and path.suffix.casefold()
        not in (".pyc", ".pyo", ".bat", ".cmd", ".log", ".bak", ".old", ".tmp", ".pdb")
        and path.name
        not in (
            "SOURCES.json",
            "BUNDLE_SOURCES.json",
            "NATIVE_BUILD.json",
            "NFSMW_RaceMap_Status.csv",
            "strip_python_comments.py",
        )
    )


def archive(directory, output, source=False):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".partial")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(directory.rglob("*")):
                rel = p.relative_to(directory)
                if not p.is_file() or p.is_symlink():
                    continue
                keep = allowed(rel) and (not source or rel.as_posix() not in GENERATED_SOURCE_FILES)
                if keep:
                    z.write(p, rel.as_posix())
        with zipfile.ZipFile(temporary) as z:
            if z.testzip():
                raise ValueError("Archive verification failed: " + output.name)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(output.name, output.stat().st_size, hashlib.sha256(output.read_bytes()).hexdigest())


def package(args):
    destination = args.destination.resolve()
    output = args.output.resolve()
    source = args.source.resolve()
    if destination.is_relative_to(source) or output.is_relative_to(source):
        raise ValueError("Use staging and output folders outside the source.")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Use an empty staging folder.")
    if (
        not (source / "world/nfsmw.apworld").is_file()
        or not (source / "client/NFSMWClient_Data/app.zip").is_file()
    ):
        subprocess.run([sys.executable, str(source / "client/tools/build.py")], check=True)
    destination.mkdir(parents=True)
    shutil.copytree(args.client_payload, destination, dirs_exist_ok=True)
    scripts = destination / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in (
        "NFSMWArchipelago.asi",
        "NFSMWArchipelago.tpk",
        "NFSMW_TurboTrap.wav",
        "NFSMW_FlashBangTrap.wav",
        "NFSMW_TruckTrap.wav",
    ):
        shutil.copy2(args.core_scripts / name, scripts / name)
    for src, name in [
        (args.setup, "NFSMW_Setup.exe"),
        (source / "NFSMW.yaml", "NFSMW.yaml"),
        (source / "world/nfsmw.apworld", "nfsmw.apworld"),
    ]:
        shutil.copy2(src, destination / name)
    source_output = (args.source_output or output.with_name(output.stem + "-Source.zip")).resolve()
    if source_output.is_relative_to(source) or source_output.is_relative_to(destination):
        raise ValueError("Keep the source download outside the source and release folders.")
    archive(source, source_output, source=True)
    archive(destination, output)
    if args.python_output:
        python_output = args.python_output.resolve()
        if python_output.is_relative_to(source) or python_output.is_relative_to(destination):
            raise ValueError("Keep the Python download outside the source and release folders.")
        with tempfile.TemporaryDirectory(
            prefix="nfsmw-python-", dir=destination.parent
        ) as temporary:
            python_stage = Path(temporary) / "Python"
            subprocess.run(
                [
                    sys.executable,
                    str(source / "client/tools/pack_python.py"),
                    str(python_stage),
                    "--core-scripts",
                    str(args.core_scripts.resolve()),
                ],
                check=True,
            )
            archive(python_stage, python_output)
    if args.portable_output:
        portable = destination.parent / (destination.name + "_manual")
        shutil.copytree(args.client_payload, portable)
        shutil.copytree(scripts, portable / "scripts")
        for name in ("NFSMW.yaml", "nfsmw.apworld"):
            shutil.copy2(destination / name, portable / name)
        archive(portable, args.portable_output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    for name in ("setup", "core-scripts", "destination", "output", "client-payload"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-output", "python-output", "portable-output"):
        parser.add_argument("--" + name, type=Path)
    package(parser.parse_args())
