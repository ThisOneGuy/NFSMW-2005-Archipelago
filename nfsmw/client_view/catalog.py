from __future__ import annotations
import csv

BUILD = "1.0.2"
HINT_STATUS = {0: "Unspecified", 10: "No priority", 20: "Avoid", 30: "Priority", 40: "Found"}


def blank_snapshot(assets=None):
    from importlib.resources import files

    assets = files(__package__).joinpath("assets")
    with (assets / "NFSMW_ShopLocations.csv").open(encoding="utf-8-sig", newline="") as stream:
        shops = [
            {
                "location_id": int(r["id"]),
                "location_type": r["type"],
                "location_name": r["name"],
                "car": r["car"],
                "category": r["category"],
                "tier": r["tier"],
                "price": None,
                "item_name": "Not connected",
                "recipient_name": "",
                "checked": False,
                "hinted": False,
                "received": False,
                "status": "Not connected",
                "randomized": None,
                "flags": 0,
            }
            for r in csv.DictReader(stream)
        ]
    with (assets / "NFSMW_ItemManifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        cars = sorted({r["car"] for r in csv.DictReader(stream) if r["type"] == "car"})
    return {
        "schema": 1,
        "build": BUILD,
        "session_id": "",
        "available": False,
        "connected": False,
        "server": "",
        "slot": "",
        "slot_id": None,
        "seed": "",
        "team": None,
        "goal": False,
        "checks": 0,
        "total_checks": 0,
        "received_count": 0,
        "hint_points": 0,
        "hint_cost": 0,
        "form_open": False,
        "cars": [{"name": c, "received": False} for c in cars],
        "shops": shops,
        "hints": [],
        "hint_items": [],
        "text": [],
    }
