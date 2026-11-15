from pathlib import Path
import csv
import importlib
import sys
from types import ModuleType
import zipfile

root = Path(__file__).resolve().parent
package = ModuleType("_nfsmw_catalog_build")
package.__path__ = [str(root / "nfsmw")]
sys.modules[package.__name__] = package
locations = importlib.import_module(package.__name__ + ".locations").LOCATION_TABLE
items = importlib.import_module(package.__name__ + ".items").ITEM_TABLE
fields = ("id", "type", "name", "car", "category", "tier", "base_price", "unlock_condition")
for target in (
    root / "nfsmw/client_view/assets/NFSMW_ShopLocations.csv",
    root.parent / "client/NFSMWClient_Data/assets/NFSMW_ShopLocations.csv",
):
    if not target.parent.is_dir():
        continue
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, row in locations.items():
            if row["type"] in ("dealership", "performance_shop"):
                writer.writerow(
                    {key: name if key == "name" else row.get(key, "") for key in fields}
                )
for target in (
    root / "nfsmw/client_view/assets/NFSMW_ItemManifest.csv",
    root.parent / "client/NFSMWClient_Data/assets/NFSMW_ItemManifest.csv",
):
    fields = ("id", "type", "name", "car", "category", "tier")
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, row in items.items():
            writer.writerow({key: name if key == "name" else row.get(key, "") for key in fields})
with zipfile.ZipFile(root / "nfsmw.apworld", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for file in sorted((root / "nfsmw").rglob("*")):
        if (
            file.is_file()
            and "__pycache__" not in file.parts
            and file.suffix not in (".pyc", ".pyo")
        ):
            archive.write(file, file.relative_to(root).as_posix())
print(root / "nfsmw.apworld")
