from pathlib import Path
import argparse
import hashlib
import json
import runpy
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_world(world_source):
    world_source = Path(world_source).resolve()
    shutil.copy2(ROOT / "source/NFSMW_Goals.py", world_source / "nfsmw/goals.py")
    event_policy = (ROOT / "source/NFSMW_EventPermits.py").read_text(encoding="utf-8")
    (world_source / "nfsmw/event_permits.py").write_text(
        event_policy.replace("from NFSMW_Goals import", "from .goals import"),
        encoding="utf-8",
    )
    for source, target in (
        ("NFSMW_HintSearch.py", "hint_search.py"),
        ("NFSMW_ViewResults.py", "results.py"),
        ("NFSMW_StoreRoutes.py", "store_routes.py"),
    ):
        shutil.copy2(
            ROOT / "source" / source, world_source / "nfsmw/client_view" / target
        )
    (world_source / "nfsmw/client_view/event_permits.py").write_text(
        event_policy.replace("from NFSMW_Goals import", "from ..goals import"),
        encoding="utf-8",
    )
    runpy.run_path(str(world_source / "build.py"), run_name="__main__")
    launcher = ROOT / "NFSMWClient_Data/launcher"
    launcher.mkdir(parents=True, exist_ok=True)
    shutil.copy2(world_source / "nfsmw.apworld", launcher / "nfsmw.apworld")


def build_client():
    data = ROOT / "NFSMWClient_Data"
    data.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        data / "app.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for folder in (ROOT / "source", ROOT / "framework"):
            for path in sorted(folder.rglob("*.py")):
                if "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(folder).as_posix())
    files = {}
    for path in sorted(data.rglob("*")):
        if (
            not path.is_file()
            or path.name == "bundle.json"
            or "user" in path.relative_to(data).parts
        ):
            continue
        content = path.read_bytes()
        files[path.relative_to(data).as_posix()] = {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = {
        "format": 1,
        "client_build": "1.0.6",
        "native_build": "1.0.6",
        "mode": "pythonw",
        "runtime": "Installed Windows x64 Python 3.11-3.13",
        "files": files,
    }
    (data / "bundle.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(data / "app.zip")


def main():
    parser = argparse.ArgumentParser(
        description="Build the NFSMW client and Archipelago world."
    )
    parser.add_argument("--world-source", type=Path, default=ROOT.parent / "world")
    args = parser.parse_args()
    build_world(args.world_source)
    build_client()


if __name__ == "__main__":
    main()
