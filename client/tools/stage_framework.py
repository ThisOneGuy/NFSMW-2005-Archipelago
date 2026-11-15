from pathlib import Path
import argparse
import io
import shutil
import tokenize

parser = argparse.ArgumentParser(
    description="Vendor the client protocol from the official Archipelago 0.6.8 source tree."
)
parser.add_argument("archipelago", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
target = root / "framework"
target.mkdir(exist_ok=True)
for name in (
    "Utils.py",
    "CommonClient.py",
    "NetUtils.py",
    "MultiServer.py",
    "BaseClasses.py",
    "Options.py",
    "settings.py",
    "ModuleUpdate.py",
):
    shutil.copy2(args.archipelago / name, target / name)
for p in (
    args.archipelago / "apmw/__init__.py",
    *(args.archipelago / "apmw/multiserver").rglob("*.py"),
):
    destination = target / p.relative_to(args.archipelago)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, destination)
(target / "worlds").mkdir(exist_ok=True)
(target / "worlds/AutoWorld.py").write_text(
    "class AutoWorldRegister(type):\n    world_types = {}\n", encoding="utf-8"
)
(target / "worlds/__init__.py").write_text(
    """from .AutoWorld import AutoWorldRegister
network_data_package = {"games": {"Need for Speed: Most Wanted": {
    "item_name_to_id": {}, "location_name_to_id": {}, "checksum": ""}}}
""",
    encoding="utf-8",
)


p = target / "NetUtils.py"
text = p.read_text()
text = text.replace("import typing\n", "import typing\nimport sys\n", 1)
text = text.replace(
    "if typing.TYPE_CHECKING:",
    'if typing.TYPE_CHECKING or getattr(sys, "_nfsmw_client_runtime", False):',
)
p.write_text(text, encoding="utf-8")
for p in target.rglob("*.py"):
    text = p.read_text(encoding="utf-8-sig")
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    p.write_text(
        tokenize.untokenize(token for token in tokens if token.type != tokenize.COMMENT),
        encoding="utf-8",
    )
licenses = root / "NFSMWClient_Data/licenses"
licenses.mkdir(parents=True, exist_ok=True)
shutil.copy2(args.archipelago / "LICENSE", licenses / "LICENSE-Archipelago.txt")
shutil.copy2(args.archipelago / "LICENSE", root / "LICENSE-Archipelago.txt")
