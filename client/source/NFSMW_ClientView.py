from __future__ import annotations
from collections import deque
import csv
import logging
from pathlib import Path
import re
import time
from NFSMW_StoreRoutes import shop_randomized
from NFSMW_EventPermits import event_permit_mode, events_available
from NFSMW_Goals import existing_blacklist_ranks
from NFSMW_ScoutAccess import visual_scout_access
from NFSMW_Garage import garage_snapshot

BUILD = "1.0.6"
HINT_STATUS = {
    0: "Unspecified",
    10: "No priority",
    20: "Avoid",
    30: "Priority",
    40: "Found",
}
ROUTINE_NFSMW = {
    "<module>",
    "__init__",
    "_load_state",
    "configure_isolated_ap_session",
    "ensure_game_launched",
    "wait_for_game_bridge",
    "sync_slot_save",
    "refresh_setup_state",
    "scout_shop_locations",
    "accept_location_preview",
    "process_location_info",
    "replay_seed_config",
    "configure_deathlink",
    "main",
}


def field(row, name, default=""):
    return (
        row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)
    )


def number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def hint_items(ctx):
    game = getattr(
        getattr(ctx, "slot_info", {}).get(getattr(ctx, "slot", None)), "game", None
    ) or getattr(ctx, "game", "")
    try:
        names = {
            str(name)
            for item, name in ctx.item_names[game].items()
            if number(item) != 1950006
        }
    except (KeyError, TypeError, AttributeError):
        names = set()
    if not names:
        names = {
            str(field(meta, "name"))
            for meta in getattr(ctx, "item_manifest", {}).values()
            if field(meta, "name")
        }
    return sorted(
        name
        for name in names
        if name and len(name) <= 500 and not any(ord(c) < 32 for c in name)
    )


def blank_snapshot(assets):
    assets = Path(assets)
    with (assets / "NFSMW_ShopLocations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
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
    with (assets / "NFSMW_ItemManifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
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
        "garage": {"available": False, "count": None, "capacity": 25, "shop_cars": [], "cars": []},
        "hint_items": [],
        "text": [],
    }


class ViewLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.records = deque(maxlen=400)
        self.sequence = 0

    def emit(self, record):
        try:
            message = re.sub(r"\x1b\[[0-9;]*m", "", record.getMessage())[:4096]
            if record.levelno < logging.WARNING:
                if record.name == "NFSMW":
                    if record.funcName in ROUTINE_NFSMW:
                        return
                    if record.funcName == "on_package" and not message.startswith(
                        "Received item"
                    ):
                        return
                    if record.funcName == "server_auth" and message.startswith(
                        "RoomInfo received"
                    ):
                        return
                    if (
                        record.funcName == "handle_game_connection"
                        and not message.startswith(
                            (
                                "Game confirmed delivery",
                                "Garage:",
                                "Game race result",
                                "NFSMW ASI disconnected",
                            )
                        )
                    ):
                        return
                if record.name == "Client" and (
                    record.funcName
                    in (
                        "consume_network_data_package",
                        "update_permissions",
                        "process_server_cmd",
                        "run_cli",
                    )
                    or record.funcName == "server_loop"
                    and message.startswith(
                        ("Please connect to", "Connecting to", "Connected")
                    )
                ):
                    return
            self.sequence += 1
            self.records.append(
                {
                    "id": self.sequence,
                    "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                    "channel": record.name,
                    "level": record.levelname,
                    "text": message,
                }
            )
        except Exception:
            pass

    def install(self):
        for name in ("Client", "NFSMW", "StreamLog"):
            logging.getLogger(name).addHandler(self)

    def uninstall(self):
        for name in ("Client", "NFSMW", "StreamLog"):
            logging.getLogger(name).removeHandler(self)


def hint_rows(ctx):
    rows = []
    values = {}
    prefix = f"_read_hints_{ctx.team}_"
    for key, entries in getattr(ctx, "stored_data", {}).items():
        if key.startswith(prefix) and isinstance(entries, (list, tuple, set)):
            for hint in entries:
                identity = tuple(
                    number(field(hint, k))
                    for k in ("finding_player", "location", "receiving_player", "item")
                )
                previous = values.get(identity)
                if (
                    previous is None
                    or field(hint, "found", False)
                    or number(field(hint, "status")) == 40
                ):
                    values[identity] = hint
    for hint in values.values():
        receiving = number(field(hint, "receiving_player"))
        finding = number(field(hint, "finding_player"))
        location = number(field(hint, "location"))
        item = number(field(hint, "item"))
        found = bool(field(hint, "found", False)) or number(field(hint, "status")) == 40
        status = 40 if found else number(field(hint, "status"))
        try:
            item_name = ctx.item_names.lookup_in_slot(item, receiving)
        except (KeyError, AssertionError, AttributeError):
            item_name = f"Item {item}"
        try:
            location_name = ctx.location_names.lookup_in_slot(location, finding)
        except (KeyError, AssertionError, AttributeError):
            location_name = f"Location {location}"
        rows.append(
            {
                "receiving_player": receiving,
                "finding_player": finding,
                "location": location,
                "item": item,
                "item_name": item_name,
                "location_name": location_name,
                "recipient_name": ctx.player_names.get(
                    receiving, f"Player {receiving}"
                ),
                "finder_name": ctx.player_names.get(finding, f"Player {finding}"),
                "entrance": str(field(hint, "entrance")),
                "found": found,
                "status": status,
                "status_name": HINT_STATUS.get(status, "Unspecified"),
                "can_update": False,
            }
        )
    return sorted(
        rows,
        key=lambda r: (
            r["found"],
            r["recipient_name"].casefold(),
            r["item_name"].casefold(),
            r["location"],
        ),
    )


def blacklist_locations(ctx):
    rows = {}
    for event in getattr(ctx, "event_map", {}).values():
        rank = number(str(field(event, "event_id")).split(".")[0])
        location = number(field(event, "location_id"))
        if 1 <= rank <= 15 and location:
            rows[location] = (rank, str(field(event, "location_name")))
    for event in getattr(ctx, "milestone_locations", ()):
        rank = number(field(event, "blacklist_rank"))
        location = number(field(event, "location_id"))
        if 1 <= rank <= 15 and location:
            rows[location] = (rank, str(field(event, "location_name")))
    for rank in range(15, 0, -1):
        base = 2600000 + (16 - rank) * 10
        rows[base + 1] = (rank, "Challenge unlocked")
        rows[base + 2] = (rank, "Rival defeated")
    return rows


def blacklist_rows(ctx):
    names = (
        "Sonny",
        "Taz",
        "Vic",
        "Izzy",
        "Big Lou",
        "Baron",
        "Earl",
        "Jewels",
        "Kaze",
        "Ming",
        "Webster",
        "JV",
        "Ronnie",
        "Bull",
        "Razor",
    )
    received = {number(field(item, "item")) for item in ctx.items_received}
    defeated = getattr(ctx, "_verified_defeated_ranks", lambda: set())()
    checked = set(ctx.checked_locations)
    in_seed = set(ctx.server_locations)
    hints = {
        r["location"]: r for r in hint_rows(ctx) if r["finding_player"] == ctx.slot
    }
    catalog = getattr(ctx, "event_hint_catalog", {})
    events = {rank: [] for rank in range(1, 16)}
    for location, (rank, name) in sorted(blacklist_locations(ctx).items()):
        if location not in in_seed:
            continue
        hint = hints.get(location, {})
        allowed, reason = visual_scout_access(ctx, location, blacklist_locations(ctx))
        reward = catalog.get(location, {}) if allowed else {}
        events[rank].append(
            {
                "location_id": location,
                "can_scout": allowed,
                "scout_blocked_reason": reason,
                "name": name,
                "checked": location in checked or bool(hint.get("found")),
                "hinted": bool(hint),
                "pending": location in getattr(ctx, "manual_hint_locations", set())
                and not hint,
                "item_name": hint.get("item_name") or reward.get("item_name", ""),
                "recipient_name": hint.get("recipient_name")
                or reward.get("recipient_name", ""),
            }
        )
    return [
        {
            "rank": rank,
            "name": names[15 - rank],
            "unlocked": 1300000 + rank in received,
            "events_unlocked": events_available(
                ctx.slot_data, ctx.items_received, rank
            ),
            "defeated": rank in defeated,
            "events": events[rank],
        }
        for rank in sorted(existing_blacklist_ranks(ctx.slot_data), reverse=True)
    ]


def snapshot(ctx, log, session_id):
    connected = bool(ctx.ap_connected())
    hints = hint_rows(ctx)
    hinted = {r["location"] for r in hints if r["finding_player"] == ctx.slot}
    received = set()
    received_cars = set()
    cars = set()
    received_ids = set()
    receipts = set()
    for meta in ctx.item_manifest.values():
        if meta.item_type == "car":
            cars.add(meta.car)
    for item in ctx.items_received:
        item_id = number(field(item, "item"))
        received_ids.add(item_id)
        receipts.add(
            (item_id, number(field(item, "location")), number(field(item, "player")))
        )
        meta = ctx.item_manifest.get(item_id)
        if meta:
            received.add((meta.item_type, meta.car, meta.category, meta.tier))
            if meta.item_type == "car":
                received_cars.add(meta.car)
    checked = set(ctx.checked_locations) | set(
        getattr(ctx, "won_race_locations", set())
    )
    queued = set(getattr(ctx, "queued_location_checks", set())) | set(
        getattr(ctx, "pending_checks", set())
    )
    server_locations = set(ctx.server_locations)
    settings = getattr(ctx, "slot_data", {}) or {}
    settings_known = bool(settings) or connected
    shops = []
    for location_id, meta in sorted(ctx.shop_locations.items()):
        can_scout, scout_reason = visual_scout_access(ctx, location_id)
        entry = ctx.shop_catalog.get(location_id, {}) if can_scout else {}
        in_seed = not server_locations or location_id in server_locations
        randomized = (
            shop_randomized(
                {
                    "location_type": meta.location_type,
                    "car": meta.car,
                    "category": meta.category,
                    "tier": meta.tier,
                },
                settings,
            )
            if settings_known
            else None
        )
        if randomized is False or not in_seed:
            entry = {}

        bought = location_id in checked
        kind = "car" if meta.location_type == "dealership" else "performance_part"
        owned = (kind, meta.car, meta.category, meta.tier) in received
        reward_id = number(entry.get("item_id"))
        recipient = number(entry.get("recipient_player"))
        reward_meta = ctx.item_manifest.get(reward_id)
        own_reward = recipient == ctx.slot
        reward_received = own_reward and (
            (reward_id, location_id, ctx.slot) in receipts
            or reward_id in received_ids
            and reward_meta is not None
            and reward_meta.item_type in ("car", "performance_part")
        )
        reward_status = (
            "Unrevealed"
            if not reward_id
            else (
                "Received"
                if reward_received
                else (
                    "Sent"
                    if not own_reward and bought
                    else (
                        "Other player"
                        if not own_reward
                        else "Awaiting delivery" if bought else "Not received"
                    )
                )
            )
        )
        item_name = (
            "Not randomized"
            if randomized is False
            else (
                "Not in this seed"
                if not in_seed
                else str(entry.get("item_name", "Not scouted yet"))
            )
        )
        if entry.get("item_id") and entry.get("recipient_player") in ctx.slot_info:
            try:
                item_name = ctx.item_names.lookup_in_slot(
                    entry["item_id"], entry["recipient_player"]
                )
            except (KeyError, AssertionError, AttributeError):
                pass
        if randomized is not False and in_seed and not can_scout:
            item_name = (
                "Reward reveals disabled"
                if not settings.get("reveal_event_rewards", False)
                else "Car not received"
            )
        status = (
            "Not randomized"
            if randomized is False
            else (
                "Not in this seed"
                if not in_seed
                else (
                    "Checked"
                    if bought
                    else (
                        "Syncing check"
                        if location_id in queued
                        else "Unchecked" if entry else "Waiting for game data" if can_scout else item_name
                    )
                )
            )
        )
        shops.append(
            {
                "location_id": location_id,
                "can_scout": can_scout,
                "scout_blocked_reason": scout_reason,
                "randomized": randomized,
                "location_type": meta.location_type,
                "location_name": meta.location_name,
                "car": meta.car,
                "category": meta.category,
                "tier": meta.tier,
                "price": entry.get("price"),
                "item_name": item_name,
                "recipient_name": str(entry.get("recipient_name", "")),
                "recipient_game": str(entry.get("recipient_game", "")),
                "item_id": entry.get("item_id"),
                "checked": bought,
                "hinted": location_id in hinted,
                "received": owned,
                "reward_received": reward_received,
                "reward_status": (
                    "Not randomized"
                    if randomized is False
                    else "Not in this seed" if not in_seed else reward_status
                ),
                "unlock_received": owned,
                "status": status,
                "flags": number(entry.get("flags")),
            }
        )
    return {
        "schema": 1,
        "build": BUILD,
        "session_id": session_id,
        "available": True,
        "connected": connected,
        "capabilities": [
            "website_links",
            "read_only_hint_status",
            "shared_hints",
            "hint_requests",
            "garage_inventory",
            "car_resend",
        ],
        "connection_phase": str(
            getattr(ctx, "connection_message", {}).get("phase", "input")
        ),
        "connection_message": str(
            getattr(ctx, "connection_message", {}).get("message", "")
        ),
        "session_bound": bool(
            getattr(ctx, "session_key", "") or getattr(ctx, "game_ready_pids", set())
        ),
        "server": str(getattr(ctx, "requested_server", "")),
        "slot": str(ctx.slot_name),
        "slot_id": ctx.slot,
        "seed": str(
            getattr(ctx, "session_seed_name", "")
            or getattr(ctx, "server_seed_name", "")
            or ""
        ),
        "team": ctx.team,
        "goal": bool(ctx.finished_game),
        "checks": len(ctx.checked_locations),
        "form_open": bool(
            getattr(ctx, "connection_screen", None) is not None
            and not ctx.connection_screen.closed
            and not getattr(ctx.connection_screen, "hidden_for_game", False)
        ),
        "total_checks": len(server_locations),
        "received_count": len(ctx.items_received),
        "hint_points": number(getattr(ctx, "hint_points", 0)),
        "hint_cost": number(getattr(ctx, "hint_cost", 0)),
        "cars": [{"name": c, "received": c in received_cars} for c in sorted(cars)],
        "blacklist_randomized": bool(
            getattr(ctx, "slot_data", {}).get("randomize_blacklist_unlocks", False)
        ),
        "blacklist_event_permits": event_permit_mode(getattr(ctx, "slot_data", {})),
        "reveal_event_rewards": bool(settings.get("reveal_event_rewards", False)),
        "blacklist_current": getattr(ctx, "current_blacklist_rank", None),
        "blacklist": blacklist_rows(ctx),
        "garage": garage_snapshot(ctx, blacklist_locations(ctx), hints),
        "shops": shops,
        "hints": hints,
        "hint_items": hint_items(ctx),
        "text": list(log.records),
    }


async def perform_action(ctx, request):
    if not ctx.ap_connected():
        return {"ok": False, "error": "Disconnected from your Archipelago session."}
    action = request.get("action")
    if action == "garage_resend":
        car = request.get("car")
        if not isinstance(car, str) or len(car) > 128:
            return {"ok": False, "operation": action, "error": "Choose a received car from Garage."}
        return await ctx.request_garage_resend(car)
    if action == "hint_request":
        name = request.get("item")
        if not isinstance(name, str) or name not in hint_items(ctx):
            return {
                "ok": False,
                "operation": action,
                "error": "Select an exact item from the matching items list.",
            }
        message = "!hint " + name
        try:
            await ctx.send_msgs([{"cmd": "Say", "text": message}])
            if not ctx.ap_connected():
                raise ConnectionError("Disconnected during hint request")
        except (OSError, RuntimeError):
            return {
                "ok": False,
                "operation": action,
                "error": "Could not send the hint request. Check your connection and retry.",
            }
        logging.getLogger("Client").info("You: %s", message)
        return {
            "ok": True,
            "operation": action,
            "item": name,
            "message": "Hint requested. Server replies also appear in Archipelago.",
        }
    if action == "command":
        value = request.get("text")
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 512
            or any(ord(c) < 32 for c in value)
        ):
            return {"ok": False, "error": "Enter one message of 1–512 characters."}
        if value.split()[0].casefold() in ("/connect", "/disconnect", "/exit", "/quit"):
            return {
                "ok": False,
                "error": "The connection is managed by the game-folder client.",
            }
        logging.getLogger("Client").info("You: %s", value)
        ctx.command_processor(ctx)(value)
        return {"ok": True}
    if action == "reveal":
        location = number(request.get("location"))
        if (
            location not in ctx.shop_locations
            and location not in blacklist_locations(ctx)
        ) or location not in ctx.server_locations:
            return {"ok": False, "error": "Choose a check from your current seed."}
        allowed, reason = visual_scout_access(ctx, location, blacklist_locations(ctx))
        if not allowed:
            return {"ok": False, "error": reason}
        revealed = ctx.__dict__.setdefault("revealed_hint_locations", set())
        manual = ctx.__dict__.setdefault("manual_hint_locations", set())
        seen = ctx.__dict__.setdefault("seen_locations", set())
        old = location in revealed
        old_seen = location in seen
        old_manual = location in manual
        revealed.add(location)
        seen.add(location)
        manual.add(location)
        if not getattr(ctx, "_save_state", lambda: True)():
            if not old:
                revealed.discard(location)
            if not old_seen:
                seen.discard(location)
            if not old_manual:
                manual.discard(location)
            return {"ok": False, "error": "Could not save this reveal. Try again."}
        await ctx.flush_seen_hints()
        return {
            "ok": True,
            "operation": "reveal",
            "message": "Hint requested. It will appear in Hints when the server replies.",
        }
    if action == "hint_status":
        return {"ok": False, "error": "Hint status is read-only in NFSMW Client."}
    return {"ok": False, "error": "Unsupported view action."}
