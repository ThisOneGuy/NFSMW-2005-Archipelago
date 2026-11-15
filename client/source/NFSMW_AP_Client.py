from __future__ import annotations
from NFSMW_ReleasePolicy import trap_allowed, cash_price
from NFSMW_EventPermits import event_permit_mode, event_permit_mask, events_available
from NFSMW_Goals import (
    goal_settings,
    goal_completed,
    goal_progress,
    goal_required,
    goal_description,
    final_escape_verified,
    free_order_blacklist,
    blacklist_exist_count,
    existing_blacklist_ranks,
)

import asyncio
import configparser
import csv
import json
import math
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional


def find_archipelago_root(script_directory: Path) -> Path:

    config = configparser.ConfigParser(interpolation=None)
    config.read(script_directory / "NFSMW_AP_Client.ini", encoding="utf-8")
    explicit = os.environ.get("NFSMW_AP_ARCHIPELAGO_ROOT", "") or config.get(
        "Runtime", "ArchipelagoRoot", fallback=""
    )
    if explicit.strip():
        configured = Path(os.path.expandvars(explicit.strip().strip('"'))).expanduser()
        candidates = [
            configured if configured.is_absolute() else script_directory / configured
        ]
    else:
        candidates = [
            script_directory,
            script_directory.parent / "framework",
            script_directory.parent,
        ]
    for candidate in candidates:
        if (
            all(
                (candidate / name).is_file()
                for name in ("Utils.py", "CommonClient.py", "BaseClasses.py")
            )
            and (candidate / "worlds").is_dir()
        ):
            return candidate.resolve()
    raise RuntimeError(
        "Archipelago source files were not found. Set [Runtime] ArchipelagoRoot "
        "in NFSMW_AP_Client.ini to the folder containing Utils.py and CommonClient.py, "
        "or reinstall the client with NFSMW_Setup.exe and launch the installed copy."
    )


def prepare_archipelago_imports() -> Path:
    if getattr(sys, "frozen", False):

        root = Path(
            getattr(sys, "_nfsmw_game_root", Path(sys.executable).resolve().parent)
        ).resolve()
        os.chdir(root)
        return root
    else:
        root = find_archipelago_root(Path(__file__).resolve().parent)
        if root == Path(__file__).resolve().parents[1] / "framework":
            sys._nfsmw_client_runtime = True
            os.environ.setdefault("SKIP_REQUIREMENTS_UPDATE", "1")
    sys.path.insert(0, str(root))

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(root)
    return root


try:
    ARCHIPELAGO_ROOT = prepare_archipelago_imports()
except RuntimeError as exc:
    raise SystemExit(str(exc)) from None

import Utils
from CommonClient import CommonContext, server_loop
from NetUtils import ClientStatus
from NFSMW_SMS import NFSMWSMSMixin
from NFSMW_RetiredFeatures import (
    cleanup_retired_assets,
    disabled_environment,
    retired_item_payload,
)
from NFSMW_Bounty import bounty_settings
from NFSMW_SaveSession import (
    select_session,
    startup_has_profile,
    prepare_player_preferences,
)

Utils.init_logging("NFSMWClient", exception_logger="Client")
logger = logging.getLogger("NFSMW")
logger.info("Client runtime directory: %s", ARCHIPELAGO_ROOT)

GAME_NAME = "Need for Speed: Most Wanted"
CLIENT_BUILD = "1.0.5"
NATIVE_BUILD = "1.0.5"


def profile_filename(value: str) -> str:
    if (
        not value
        or len(value) > 31
        or not value.isascii()
        or value in (".", "..")
        or value[-1] in ". "
        or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value)
        or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value)
    ):
        raise ValueError(
            "Slot/profile name must be a valid Windows filename of 1–31 ASCII characters."
        )
    return value


def session_save_identity(
    server: str, seed: str, slot: str, team: int = 0
) -> tuple[str, dict]:
    from urllib.parse import urlsplit

    address = normalize_server_address(server)
    if not address:
        raise RuntimeError(
            "An authenticated server address is required before opening a Career save."
        )
    parsed = urlsplit(address if "://" in address else "ws://" + address)
    host = parsed.hostname.casefold()
    port = parsed.port or (443 if parsed.scheme == "wss" else 38281)
    authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    route = "" if parsed.path in ("", "/") else parsed.path
    identity = {
        "version": 2,
        "server": authority + route + ("?" + parsed.query if parsed.query else ""),
        "seed": seed,
        "slot": profile_filename(slot),
        "team": team,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()

    return "session_v2_" + digest, identity


def validate_session_save_root(base: Path, root: Path, identity: dict) -> None:
    if len(str(root / "NFS Most Wanted" / identity["slot"] / identity["slot"])) >= 250:
        raise RuntimeError(
            "The isolated save path is too long for NFSMW. Shorten Launcher.SaveRoot before launching."
        )
    expected = base.resolve() / root.name
    if root.is_symlink() or root.resolve() != expected:
        raise RuntimeError(
            "The session save directory links outside its own server/seed namespace."
        )
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "NFSMW_AP_Session.json"
    if manifest.is_symlink():
        raise RuntimeError("The session identity file must not be a link.")
    if manifest.exists():
        if json.loads(manifest.read_text(encoding="utf-8")) != identity:
            raise RuntimeError(
                "The save directory belongs to a different server, seed, team or slot."
            )
    else:
        if any(root.iterdir()):
            raise RuntimeError(
                "Refusing an existing save directory with no matching session identity."
            )
        try:
            with manifest.open("x", encoding="utf-8") as output:
                json.dump(identity, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if json.loads(manifest.read_text(encoding="utf-8")) != identity:
                raise RuntimeError("The save directory was bound to another session.")
    save_root = root / "NFS Most Wanted"
    if save_root.is_symlink() or save_root.resolve() != expected / "NFS Most Wanted":
        raise RuntimeError("The game save folder links to another session.")
    slot = identity["slot"]
    for path in (save_root / slot, save_root / slot / slot):
        if path.is_symlink():
            raise RuntimeError("The slot save path must not link to another session.")
        path.resolve().relative_to(expected)


def game_binding(
    hello: dict[str, Any], setup_token: str, session_key: str, setup_running: bool
) -> tuple[bool, bool]:
    if not isinstance(hello, dict):
        raise ValueError("Expected a game hello object.")
    setup = hello.get("setup") is True
    pid = _safe_int(hello.get("process_id", 0))
    owned_setup = (
        setup
        and setup_running
        and bool(setup_token)
        and pid > 0
        and hello.get("setup_token") == setup_token
    )
    bound_game = (
        not setup and bool(session_key) and hello.get("session_key") == session_key
    )
    if (
        hello.get("type") != "hello"
        or _safe_int(hello.get("ui_protocol", 0)) != 2
        or not (owned_setup or bound_game)
    ):
        raise ValueError(
            "Game process is not bound to this AP session with the current ASI."
        )
    return owned_setup, bound_game


BLACKLIST_NAMES = {
    15: "Sonny",
    14: "Taz",
    13: "Vic",
    12: "Izzy",
    11: "Big Lou",
    10: "Baron",
    9: "Earl",
    8: "Jewels",
    7: "Kaze",
    6: "Ming",
    5: "Webster",
    4: "JV",
    3: "Ronnie",
    2: "Bull",
    1: "Razor",
}

HERE = (
    Path(
        getattr(sys, "_nfsmw_game_root", Path(sys.executable).resolve().parent)
    ).resolve()
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
ASSET_ROOT = (
    Path(sys._MEIPASS) / "assets"
    if getattr(sys, "frozen", False)
    else (
        HERE.parent / "NFSMWClient_Data/assets"
        if (HERE.parent / "NFSMWClient_Data/assets").is_dir()
        else HERE
    )
)
EVENT_MAP_CSV = ASSET_ROOT / "NFSMW_EventMap.csv"
SHOP_CSV = ASSET_ROOT / "NFSMW_ShopLocations.csv"
MILESTONE_CSV = ASSET_ROOT / "NFSMW_MilestoneLocations.csv"
ITEM_CSV = ASSET_ROOT / "NFSMW_ItemManifest.csv"
DISCOVERY_CSV = HERE / "NFSMW_EventDiscovery.csv"
CAREER_PROBE_CSV = HERE / "NFSMW_CareerEventProbe.csv"
MILESTONE_DECODED_CSV = HERE / "NFSMW_MilestoneDecoded.csv"
MILESTONE_METRIC_CSV = HERE / "NFSMW_MilestoneMetricProgress.csv"
MILESTONE_STRING_CSV = HERE / "NFSMW_MilestoneMetricStrings.csv"
SAVE_RANK_CSV = HERE / "NFSMW_SaveRankProbe.csv"
SHOP_CACHE_JSON = HERE / "NFSMW_AP_ShopCache.json"
STATE_JSON = HERE / "NFSMW_AP_ClientState.json"


def _car_compare_key(value: str) -> str:
    text = str(value or "").replace("Ã©", "e").replace("é", "e")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch.lower() for ch in text if ch.isascii() and ch.isalnum())


@dataclass(frozen=True)
class EventMapping:
    event_id: str
    location_id: int
    location_name: str
    mapping_source: str


@dataclass(frozen=True)
class ShopLocation:
    location_id: int
    location_type: str
    location_name: str
    car: str
    category: str
    tier: str
    base_price: int


@dataclass(frozen=True)
class ItemMeta:
    item_id: int
    item_type: str
    name: str
    car: str
    category: str
    tier: str


@dataclass(frozen=True)
class MilestoneLocation:
    location_id: int
    location_name: str
    blacklist_rank: int
    category: str
    tier: str


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def load_event_map(path: Path) -> dict[str, EventMapping]:
    mappings: dict[str, EventMapping] = {}
    if not path.exists():
        logger.warning("Event map not found: %s", path)
        return mappings

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            event_id = (row.get("event_id") or "").strip()
            if not event_id:
                continue
            mappings[event_id] = EventMapping(
                event_id=event_id,
                location_id=_safe_int(row.get("location_id")),
                location_name=(row.get("location_name") or "").strip(),
                mapping_source=(row.get("mapping_source") or "unknown").strip(),
            )
    return mappings


def load_shop_locations(path: Path) -> dict[int, ShopLocation]:
    locations: dict[int, ShopLocation] = {}
    if not path.exists():
        logger.warning("Shop location manifest not found: %s", path)
        return locations

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            location_id = _safe_int(row.get("id") or row.get("location_id"))
            if not location_id:
                continue
            location_type = (row.get("type") or row.get("location_type") or "").strip()
            if location_type not in {"dealership", "performance_shop"}:
                continue
            locations[location_id] = ShopLocation(
                location_id=location_id,
                location_type=location_type,
                location_name=(
                    row.get("name") or row.get("location_name") or ""
                ).strip(),
                car=(row.get("car") or "").strip(),
                category=(row.get("category") or "").strip(),
                tier=(row.get("tier") or "").strip(),
                base_price=_safe_int(row.get("base_price")),
            )
    return locations


def load_item_manifest(path: Path) -> dict[int, ItemMeta]:
    items: dict[int, ItemMeta] = {}
    if not path.exists():
        logger.warning("Item manifest not found: %s", path)
        return items

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            item_id = _safe_int(row.get("id") or row.get("item_id"))
            if not item_id:
                continue
            items[item_id] = ItemMeta(
                item_id=item_id,
                item_type=(row.get("type") or row.get("item_type") or "").strip(),
                name=(row.get("name") or "").strip(),
                car=(row.get("car") or "").strip(),
                category=(row.get("category") or "").strip(),
                tier=(row.get("tier") or "").strip(),
            )
    return items


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_milestone_locations(path: Path) -> list[MilestoneLocation]:
    rows: list[MilestoneLocation] = []

    if not path.exists():
        logger.warning("Milestone location manifest not found: %s", path)
        return rows

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            location_id = _safe_int(row.get("id") or row.get("location_id"))
            blacklist_rank = _safe_int(row.get("blacklist_rank"))

            if not location_id or not (1 <= blacklist_rank <= 15):
                continue

            rows.append(
                MilestoneLocation(
                    location_id=location_id,
                    location_name=(
                        row.get("name") or row.get("location_name") or ""
                    ).strip(),
                    blacklist_rank=blacklist_rank,
                    category=(row.get("category") or "").strip(),
                    tier=(row.get("tier") or "").strip(),
                )
            )

    return rows


def _first_number(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def milestone_target(location: MilestoneLocation) -> tuple[str, Optional[float]]:
    tier = location.tier

    if location.category == "Pursuit Time":
        value = _first_number(tier)
        return ">=", None if value is None else value * 60.0

    if location.category == "Pursuit Evasion":
        value = _first_number(tier)
        return "<", None if value is None else value * 60.0

    if location.category == "Photo Ticket":
        value = _first_number(tier)
        return ">=", value

    value = _first_number(tier)
    return ">=", value


def metric_satisfies(
    location: MilestoneLocation,
    value: float,
) -> Optional[bool]:
    operator, target = milestone_target(location)

    if target is None:
        return None

    if operator == "<":
        return value < target

    return value >= target


def _candidate_save_roots() -> list[Path]:

    roots: list[Path] = []

    homes: list[Path] = [Path.home()]

    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        homes.append(Path(user_profile))

    for home in homes:
        for candidate in (
            home / "Documents" / "NFS Most Wanted",
            home / "OneDrive" / "Documents" / "NFS Most Wanted",
        ):
            if candidate not in roots:
                roots.append(candidate)

    return roots


def probe_current_blacklist_rank(
    save_roots: Optional[list[Path]] = None,
) -> tuple[Optional[int], Optional[Path]]:

    rank_offset = 0x4038
    candidates: list[tuple[float, Path, int, int]] = []

    roots = save_roots if save_roots is not None else _candidate_save_roots()

    for root in roots:
        if not root.exists():
            continue

        try:
            paths = list(root.rglob("*"))
        except OSError as exc:
            logger.debug("Could not scan NFSMW save root %s: %s", root, exc)
            continue

        for path in paths:
            try:
                if not path.is_file():
                    continue

                stat = path.stat()
                if stat.st_size <= rank_offset:
                    continue

                with path.open("rb") as f:
                    f.seek(rank_offset)
                    raw = f.read(1)

                if len(raw) != 1:
                    continue

                rank = raw[0]

                if not (1 <= rank <= 15):
                    continue

                candidates.append(
                    (
                        stat.st_mtime,
                        path,
                        rank,
                        stat.st_size,
                    )
                )
            except OSError:
                continue

    try:
        with SAVE_RANK_CSV.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "modified_time",
                    "path",
                    "size_bytes",
                    "rank_byte_0x4038",
                    "selected",
                ]
            )

            newest = max(candidates, default=None, key=lambda row: row[0])

            for modified, path, rank, size in sorted(
                candidates,
                key=lambda row: row[0],
                reverse=True,
            ):
                writer.writerow(
                    [
                        time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(modified),
                        ),
                        str(path),
                        size,
                        rank,
                        "yes" if newest and path == newest[1] else "",
                    ]
                )
    except OSError as exc:
        logger.warning("Could not write save-rank probe CSV: %s", exc)

    if not candidates:
        logger.warning(
            "No NFSMW v1.3 save candidate with a valid rank byte at "
            "offset 0x4038 was found. Career rank will be read from the game after launch."
        )
        return None, None

    modified, path, rank, size = max(
        candidates,
        key=lambda row: row[0],
    )

    logger.info(
        "READ-ONLY NFSMW save-rank probe selected newest save: %s "
        "(size=%d, byte[0x4038]=%d => current Blacklist rank candidate #%d).",
        path,
        size,
        rank,
        rank,
    )

    if len(candidates) > 1:
        logger.info(
            "Save-rank probe found %d valid save candidate(s); "
            "NFSMW_SaveRankProbe.csv lists them all.",
            len(candidates),
        )

    return rank, path


def append_discovery_row(
    event_id: str, source: str, ranking: str = "", won: str = ""
) -> None:
    new_file = not DISCOVERY_CSV.exists()
    with DISCOVERY_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["event_id", "source", "ranking", "won"])
        writer.writerow([event_id, source, ranking, won])


def append_career_probe_row(msg: dict[str, Any]) -> None:
    new_file = not CAREER_PROBE_CSV.exists()

    with CAREER_PROBE_CSV.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.writer(f)

        if new_file:
            writer.writerow(
                [
                    "event_name",
                    "event_hash",
                    "event_handle",
                    "raw_dwords",
                    "pointer_ascii",
                    "pointer_dwords",
                ]
            )

        writer.writerow(
            [
                str(msg.get("event_name", "")),
                str(msg.get("event_hash", "")),
                str(msg.get("event_handle", "")),
                str(msg.get("raw_dwords", "")),
                str(msg.get("pointer_ascii", "")),
                str(msg.get("pointer_dwords", "")),
            ]
        )


def append_milestone_metric_row(msg: dict[str, Any]) -> None:
    new_file = not MILESTONE_METRIC_CSV.exists()

    with MILESTONE_METRIC_CSV.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.writer(f)

        if new_file:
            writer.writerow(
                [
                    "event_name",
                    "metric_name",
                    "ap_category",
                    "value_float",
                    "descriptor",
                    "source_hash",
                    "source_name",
                    "payload_pointer",
                ]
            )

        writer.writerow(
            [
                str(msg.get("event_name", "")),
                str(msg.get("metric_name", "")),
                str(msg.get("ap_category", "")),
                str(msg.get("value_float", "")),
                str(msg.get("descriptor", "")),
                str(msg.get("source_hash", "")),
                str(msg.get("source_name", "")),
                str(msg.get("payload_pointer", "")),
            ]
        )


def append_milestone_metric_string_row(msg: dict[str, Any]) -> None:
    new_file = not MILESTONE_STRING_CSV.exists()

    with MILESTONE_STRING_CSV.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.writer(f)

        if new_file:
            writer.writerow(
                [
                    "address",
                    "text",
                ]
            )

        writer.writerow(
            [
                str(msg.get("address", "")),
                str(msg.get("text", "")),
            ]
        )


def append_milestone_decoded_row(msg: dict[str, Any]) -> None:
    new_file = not MILESTONE_DECODED_CSV.exists()

    with MILESTONE_DECODED_CSV.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.writer(f)

        if new_file:
            writer.writerow(
                [
                    "event_name",
                    "outer_hash",
                    "payload_pointer",
                    "payload_hash",
                    "source_hash",
                    "source_name",
                    "size_or_type",
                    "flags",
                    "descriptor",
                    "value_bits",
                    "value_float",
                    "descriptor_dwords",
                    "descriptor_ascii",
                ]
            )

        writer.writerow(
            [
                str(msg.get("event_name", "")),
                str(msg.get("outer_hash", "")),
                str(msg.get("payload_pointer", "")),
                str(msg.get("payload_hash", "")),
                str(msg.get("source_hash", "")),
                str(msg.get("source_name", "")),
                str(msg.get("size_or_type", "")),
                str(msg.get("flags", "")),
                str(msg.get("descriptor", "")),
                str(msg.get("value_bits", "")),
                str(msg.get("value_float", "")),
                str(msg.get("descriptor_dwords", "")),
                str(msg.get("descriptor_ascii", "")),
            ]
        )


def completed_milestone_location(
    msg: dict[str, Any], locations: list[MilestoneLocation]
) -> Optional[MilestoneLocation]:
    if (
        msg.get("event_name") != "MilestoneCompleted"
        or msg.get("career_mode") is not True
        or _safe_int(msg.get("milestone_state", 0)) != 4
    ):
        return None
    try:
        key = int(str(msg.get("milestone_key", "")), 16)
        type_key = int(str(msg.get("milestone_type_key", "")), 16)
    except (ValueError, TypeError):
        return None
    categories = {
        0x850A64BC: "Trade Paint",
        0x2377E50D: "Bounty",
        0x5392E4FD: "Pursuit Evasion",
        0x033FA23A: "Pursuit Time",
        0xDCFC0710: "Cost to State",
        0xFD989A3A: "Cost to State",
        0xEB45F99D: "Roadblock",
        0xA61CAC24: "Infractions",
        0xCDF36FC2: "Spike Strip",
    }
    category = categories.get(type_key)
    if not 0 < key <= 0xFFFFFFFF or not category or category != msg.get("ap_category"):
        return None
    location_id = _safe_int(msg.get("target_location_id", 0))
    rank = _safe_int(msg.get("blacklist_rank", 0))
    required = _safe_float(msg.get("required_value"), float("nan"))
    value = _safe_float(msg.get("value_float"), float("nan"))
    for row in locations:
        if (
            row.location_id != location_id
            or row.blacklist_rank != rank
            or row.category != category
        ):
            continue
        _, target = milestone_target(row)
        if (
            target is not None
            and math.isfinite(required)
            and required > 0
            and abs(required - target) < 0.001
            and math.isfinite(value)
            and value >= 0
        ):
            return row
    return None


def completed_photo_location(
    msg: dict[str, Any], locations: list[MilestoneLocation]
) -> Optional[MilestoneLocation]:
    if (
        msg.get("event_name") != "PhotoTrapCompleted"
        or msg.get("career_mode") is not True
        or msg.get("camera_completed") is not True
        or msg.get("ap_category") != "Photo Ticket"
    ):
        return None
    try:
        camera_key = int(str(msg.get("camera_key", "")), 16)
    except (ValueError, TypeError):
        return None
    if not 0 < camera_key <= 0xFFFFFFFF:
        return None
    location_id = _safe_int(msg.get("target_location_id", 0))
    rank = _safe_int(msg.get("blacklist_rank", 0))
    required = _safe_float(msg.get("required_speed_mph"), float("nan"))
    value = _safe_float(msg.get("value_float"), float("nan"))
    for row in locations:
        if (
            row.location_id != location_id
            or row.blacklist_rank != rank
            or row.category != "Photo Ticket"
        ):
            continue
        _, target = milestone_target(row)
        if (
            target is not None
            and math.isfinite(required)
            and required > 0
            and abs(required - target) <= 1.05
            and math.isfinite(value)
            and abs(value - target) < 0.001
        ):
            return row
    return None


class NFSMWDeathLinkMixin:
    def deathlink_enabled(self) -> bool:
        return self.slot_data.get("death_link", False) in (True, 1)

    async def configure_deathlink(self) -> None:
        enabled = self.deathlink_enabled()
        await self.update_death_link(enabled)
        if not enabled and getattr(self, "deathlink_pending", {}):
            self.deathlink_pending.clear()
            self._save_state()
        await self.replay_deathlink()
        logger.info(
            "DeathLink ON (seed YAML): arrests send; incoming links raise heat to the Career cap and request police."
            if enabled
            else "DeathLink OFF (seed YAML): arrests and incoming effects are disabled."
        )

    def on_deathlink(self, data: dict[str, Any]) -> None:
        if (
            not self.deathlink_enabled()
            or not self.ap_connected()
            or not self.session_key
        ):
            return
        try:
            stamp = float(data.get("time", float("nan")))
        except (ValueError, TypeError):
            return
        source = data.get("source")
        if (
            not math.isfinite(stamp)
            or stamp <= 0
            or not isinstance(source, str)
            or not source
            or len(source) > 200
        ):
            return
        local_name = self.player_names.get(self.slot, self.slot_name)
        if source == local_name or stamp == getattr(self, "last_death_link", None):
            return
        key = hashlib.sha256(
            (self.session_key + "|" + source + "|" + repr(stamp)).encode()
        ).hexdigest()
        if key in self.deathlink_seen:
            return
        super().on_deathlink(data)
        self.deathlink_seen.add(key)
        self.deathlink_pending[key] = {
            "type": "deathlink_received",
            "id": key,
            "source": source,
            "session_key": self.session_key,
        }
        self._save_state()
        asyncio.create_task(self.replay_deathlink())

    async def replay_deathlink(self) -> None:
        if not self.session_key or not self._session_state_loaded:
            return
        enabled = self.deathlink_enabled()
        await self.broadcast(
            {
                "type": "deathlink_config",
                "enabled": enabled,
                "session_key": self.session_key,
            }
        )
        if enabled:
            for packet in list(self.deathlink_pending.values()):
                await self.broadcast(packet)

    async def send_arrest_deathlink(self, msg: dict[str, Any]) -> None:
        event = str(msg.get("event_id", ""))
        pursuit = msg.get("pursuit_id")
        if (
            msg.get("native_busted") is not True
            or not isinstance(pursuit, str)
            or not 0 < len(pursuit) <= 96
        ):
            return
        pursuit_receipt = "pursuit:" + pursuit
        if (
            pursuit_receipt in self.deathlink_bust_seen
            or not event
            or len(event) > 128
            or msg.get("session_key") != self.session_key
            or msg.get("career_mode") is not True
            or event in self.deathlink_bust_seen
        ):
            return
        self.deathlink_bust_seen.update((event, pursuit_receipt))

        if not self._save_state():
            logger.warning(
                "DeathLink sent-event receipt could not be saved; duplicate guard remains active in this client."
            )
        if not self.deathlink_enabled() or not self.ap_connected():
            logger.info(
                "DeathLink arrest not broadcast: disabled or disconnected (no stale-death replay)."
            )
            return
        try:
            await self.send_death(
                f"{self.slot_name} was arrested in Need for Speed: Most Wanted."
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "DeathLink arrest send failed; not queued for a stale replay: %s", exc
            )
            return
        await self.broadcast(
            {"type": "deathlink_sent", "session_key": self.session_key}
        )

    async def authorize_deathlink(self, msg: dict[str, Any]) -> None:
        if msg.get("session_key") != self.session_key or not self.deathlink_enabled():
            return
        key, runtime = msg.get("id"), msg.get("runtime_id")
        if (
            not isinstance(key, str)
            or not 0 < len(key) <= 128
            or not isinstance(runtime, str)
            or not 0 < len(runtime) <= 96
        ):
            return
        claims = self.deathlink_claims
        owner = claims.get(key)
        allowed = owner == runtime
        if owner is None and key in self.deathlink_pending:
            packet = self.deathlink_pending.pop(key)
            claims[key] = runtime
            if not self._save_state():
                del claims[key]
                self.deathlink_pending[key] = packet
                logger.warning(
                    "DeathLink not started: could not persist single-use authorization."
                )
                return
            allowed = True
        await self.broadcast(
            {
                "type": "deathlink_start",
                "id": key,
                "runtime_id": runtime,
                "authorized": allowed,
                "session_key": self.session_key,
            }
        )

    def confirm_deathlink(self, msg: dict[str, Any]) -> None:
        if msg.get("session_key") != self.session_key:
            return
        key = str(msg.get("id", ""))
        packet = self.deathlink_pending.pop(key, None)
        result = msg.get("result", "completed")
        logger.info("DeathLink terminal result: %s", result)
        if packet is None:
            return
        previous = self.deathlink_claims.get(key)
        runtime = msg.get("runtime_id")
        self.deathlink_claims[key] = (
            runtime
            if isinstance(runtime, str) and 0 < len(runtime) <= 96
            else "terminal"
        )
        if not self._save_state():
            self.deathlink_pending[key] = packet
            if previous is None:
                self.deathlink_claims.pop(key, None)
            else:
                self.deathlink_claims[key] = previous


class NFSMWContext(NFSMWDeathLinkMixin, NFSMWSMSMixin, CommonContext):
    game = GAME_NAME
    items_handling = 0b111
    want_slot_data = True

    def __init__(
        self,
        server_address: Optional[str],
        password: Optional[str],
        slot_name: str,
        *,
        auto_launch_game: bool = True,
        game_exe: Optional[Path] = None,
        save_base_root: Optional[Path] = None,
        enable_milestone_checks: bool = True,
        enable_photo_ticket_checks: bool = True,
        expected_seed_name: str = "",
    ) -> None:
        super().__init__(server_address, password)
        self.in_game_connect = True
        self.ap_launcher_ui = False
        self.connection_screen = None
        self.setup_game_process = None
        self.setup_token = ""
        self.setup_native_pids: set[int] = set()
        self.setup_ui_ready = False
        self.setup_launched_at = 0.0
        self.setup_ui_warning = False
        self.session_rejected = False
        self.setup_finishing = False
        self.setup_request_id = 1000000
        self.requested_server = normalize_server_address(server_address or "")
        self.connection_message = {
            "type": "connection_status",
            "phase": "input",
            "message": "Enter your server address and exact slot name.",
            "first_car": "",
        }
        self.slot_name = slot_name
        self.slot_data: dict[str, Any] = {}
        self.game_writers: set[asyncio.StreamWriter] = set()
        self.game_ready_pids: set[int] = set()
        self.game_launch_failed = False
        self.game_log_before_launch = None
        self.deathlink_claims: dict[str, str] = {}
        self.deathlink_pending: dict[str, dict[str, Any]] = {}
        self.deathlink_seen: set[str] = set()
        self.deathlink_bust_seen: set[str] = set()

        self.auto_launch_game = auto_launch_game
        self.game_exe = game_exe or Path()
        self.save_base_root = save_base_root or (
            Path.home() / "Documents" / "Archipelago" / "NFSMW"
        )

        self.enable_milestone_checks = enable_milestone_checks
        self.enable_photo_ticket_checks = enable_photo_ticket_checks
        self.expected_seed_name = expected_seed_name.strip()

        self.event_map = load_event_map(EVENT_MAP_CSV)
        self.event_map_by_rank_index: dict[tuple[int, int], EventMapping] = {}
        for _mapping in self.event_map.values():

            if _mapping.mapping_source == "rival_race":
                continue
            _match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", _mapping.event_id)
            if not _match:
                continue
            _key = (int(_match.group(1)), int(_match.group(2)))
            if _key not in self.event_map_by_rank_index:
                self.event_map_by_rank_index[_key] = _mapping

        self.shop_locations = load_shop_locations(SHOP_CSV)
        self.item_manifest = load_item_manifest(ITEM_CSV)
        self.milestone_locations = load_milestone_locations(MILESTONE_CSV)
        self.event_location_ranks = {
            row.location_id: self._blacklist_rank_from_event(row.event_id)
            for row in self.event_map.values()
            if row.mapping_source == "career_race"
        }
        self.event_location_ranks.update(
            (row.location_id, row.blacklist_rank) for row in self.milestone_locations
        )
        self.rival_mappings_by_rank: dict[int, list[EventMapping]] = {}
        for _mapping in self.event_map.values():
            if _mapping.mapping_source != "rival_race":
                continue
            _match = re.match(r"^(\d+)\.", _mapping.event_id)
            if not _match:
                continue
            _rank = int(_match.group(1))
            self.rival_mappings_by_rank.setdefault(_rank, []).append(_mapping)
        for _rows in self.rival_mappings_by_rank.values():
            _rows.sort(key=lambda row: row.location_id)

        self.current_blacklist_rank: Optional[int] = None
        self.current_save_path: Optional[Path] = None
        self.native_profile_seen = False
        self.current_profile_name = ""
        self._save_observation = None
        self._slot_save_digest = ""
        self._slot_save_announced = False
        self._live_rank_observed_at = 0.0

        self.ap_documents_root: Optional[Path] = None
        self.session_seed_name = ""
        self.session_key = ""
        self.session_identity: dict[str, Any] = {}
        self.game_process: Optional[subprocess.Popen[Any]] = None

        self.shop_catalog: dict[int, dict[str, Any]] = {}
        self.pending_checks: set[int] = set()
        self.shop_purchase_results: dict[tuple[int, int], dict[str, Any]] = {}
        self.queued_location_checks: set[int] = set()
        self.defeated_blacklist_ranks: set[int] = set()
        self.blacklist_defeat_proofs: dict[int, dict[str, Any]] = {}
        self.final_escape_proof = {}
        self._goal_sync_lock = asyncio.Lock()
        self._goal_announced = False
        self._goal_progress_announced = -1
        self.pending_received: dict[int, dict[str, Any]] = {}
        self.known_received: dict[int, dict[str, Any]] = {}
        self.sms_pending: dict[str, dict[str, Any]] = {}
        self.sms_acknowledged: set[str] = set()
        self.reward_catalog: dict[int, dict[str, Any]] = {}
        self.event_hint_catalog: dict[int, dict[str, str]] = {}
        self.seen_locations: set[int] = set()
        self.revealed_hint_locations: set[int] = set()
        self.manual_hint_locations: set[int] = set()
        self.reward_aliases: dict[str, int] = {}
        self.reward_alias_evidence: dict[str, dict[str, Any]] = {}
        self.won_race_locations: set[int] = set()
        self._hint_retry_at: dict[int, float] = {}
        self._scout_retry_at: dict[int, float] = {}
        self._check_retry_at: dict[int, float] = {}
        self.delivered_received_indices: set[int] = set()

        self.state_json_path: Path = STATE_JSON
        self._session_state_loaded = False
        self._ap_authenticated = False

        self.milestone_trigger_scheduled: set[int] = set()
        self._last_rank_probe_monotonic = 0.0

        career_races = sum(
            1 for m in self.event_map.values() if m.mapping_source == "career_race"
        )
        rival_races = sum(
            1 for m in self.event_map.values() if m.mapping_source == "rival_race"
        )

        logger.info(
            "NFSMW client %s loaded: %d race mappings (%d Career + %d Blacklist rival), "
            "%d AP shop locations, %d NFSMW item definitions.",
            CLIENT_BUILD,
            len(self.event_map),
            career_races,
            rival_races,
            len(self.shop_locations),
            len(self.item_manifest),
        )

        if career_races != 131:
            logger.error(
                "RACE MAP INCOMPLETE: expected 131 Career races, got %d.",
                career_races,
            )
        else:
            logger.info(
                "ALL 131 NORMAL CAREER RACES ARE PRESENT IN NFSMW_EventMap.csv."
            )

        logger.info(
            "Milestone manifest loaded: %d locations across ranks 1-15. "
            "Current rank candidate: %s.",
            len(self.milestone_locations),
            (
                f"#{self.current_blacklist_rank}"
                if self.current_blacklist_rank is not None
                else "<unknown>"
            ),
        )

    def _load_state(self) -> None:
        path = self.state_json_path

        self.delivered_received_indices.clear()
        self.native_profile_seen = False
        self.queued_location_checks.clear()
        self.defeated_blacklist_ranks = set()
        self.blacklist_defeat_proofs = {}
        self.final_escape_proof = {}
        self._goal_announced = False
        self._goal_progress_announced = -1
        self.finished_game = False
        self.pending_checks.clear()
        self.shop_purchase_results.clear()
        self.pending_received.clear()
        self.known_received.clear()
        self.reward_catalog = {}
        self.shop_catalog = {}
        self.event_hint_catalog = {}
        self._shop_catalog_reported_count = 0
        self.seen_locations = set()
        self.revealed_hint_locations = set()
        self.manual_hint_locations = set()
        self.reward_aliases = {}
        self.reward_alias_evidence = {}
        self.won_race_locations = set()
        self._hint_retry_at = {}
        self._scout_retry_at = {}
        self._check_retry_at = {}
        self.deathlink_claims = {}
        self.deathlink_pending = {}
        self.deathlink_seen = set()
        self.deathlink_bust_seen = set()

        if not path.exists():
            self._session_state_loaded = True
            logger.info(
                "No previous seed-scoped client state exists yet: %s",
                path,
            )
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            if (
                data.get("slot") != self.slot_name
                or data.get("session_key") != self.session_key
            ):
                logger.warning(
                    "Ignoring client-state file whose seed/slot identity "
                    "does not match this AP session: %s",
                    path,
                )
                self._session_state_loaded = True
                return

            self.delivered_received_indices = {
                int(x)
                for x in data.get(
                    "delivered_received_indices",
                    [],
                )
            }

            self.native_profile_seen = data.get("native_profile_seen") is True
            self.queued_location_checks = {
                int(x)
                for x in data.get(
                    "queued_location_checks",
                    [],
                )
            }

            self.deathlink_seen = {
                str(x) for x in data.get("deathlink_seen", []) if isinstance(x, str)
            }
            sent = data.get("deathlink_bust_seen", [])
            if isinstance(sent, list):
                self.deathlink_bust_seen = {
                    x for x in sent if isinstance(x, str) and 0 < len(x) <= 128
                }
            claims = data.get("deathlink_claims", {})
            if isinstance(claims, dict):
                self.deathlink_claims = {
                    k: v
                    for k, v in claims.items()
                    if isinstance(k, str)
                    and 0 < len(k) <= 128
                    and isinstance(v, str)
                    and 0 < len(v) <= 96
                }
            queued = data.get("deathlink_pending", {})
            if isinstance(queued, dict):
                self.deathlink_pending = {
                    key: packet
                    for key, packet in queued.items()
                    if isinstance(key, str)
                    and isinstance(packet, dict)
                    and packet.get("id") == key
                    and packet.get("session_key") == self.session_key
                    and packet.get("type") == "deathlink_received"
                    and key not in self.deathlink_claims
                }
            self._session_state_loaded = True

            logger.info(
                "Loaded seed-scoped AP client state: %d received indices, "
                "%d queued checks (%s).",
                len(self.delivered_received_indices),
                len(self.queued_location_checks),
                path,
            )
            self.defeated_blacklist_ranks = {
                int(x)
                for x in data.get("defeated_blacklist_ranks", [])
                if 1 <= int(x) <= 15
            }
            self.blacklist_defeat_proofs = {
                int(k): v
                for k, v in data.get("blacklist_defeat_proofs", {}).items()
                if str(k).isdigit() and 1 <= int(k) <= 15 and isinstance(v, dict)
            }
            proof = data.get("final_escape_proof", {})
            self.final_escape_proof = (
                proof
                if final_escape_verified(proof, self.session_key, self.slot_data)
                else {}
            )
            self.load_sms_state(data)
            self.reward_catalog = {
                int(k): v
                for k, v in data.get("reward_catalog", {}).items()
                if isinstance(v, dict)
                and v.get("session_key") == self.session_key
                and v.get("location_id") == int(k)
                and v.get("location_type") in ("race", "milestone")
            }
            self.shop_catalog = {
                int(k): v
                for k, v in data.get("shop_catalog", {}).items()
                if isinstance(v, dict) and v.get("location_id") == int(k)
            }
            self.won_race_locations = {
                int(x) for x in data.get("won_race_locations", [])
            }
            self.seen_locations = {
                int(x) for x in data.get("seen_locations", []) if int(x) > 0
            }
            self.revealed_hint_locations = {
                int(x) for x in data.get("revealed_hint_locations", []) if int(x) > 0
            }
            self.manual_hint_locations = {
                int(x) for x in data.get("manual_hint_locations", []) if int(x) > 0
            }
            self.reward_aliases = {}
            self.reward_alias_evidence = {}
            if data.get("reward_alias_version") == 4:
                for alias, location in data.get("reward_aliases", {}).items():
                    if not isinstance(alias, str) or len(alias) > 256:
                        continue
                    fields = alias.split("|", 4)
                    if len(fields) != 5:
                        continue
                    event, activity, rank, track, index = fields
                    row = self.event_map.get(
                        next(
                            (
                                key
                                for key, value in self.event_map.items()
                                if value.location_id == location
                            ),
                            "",
                        )
                    )
                    if row is None:
                        continue
                    evidence = data.get("reward_alias_evidence", {}).get(alias, {})
                    if not isinstance(evidence, dict):
                        continue
                    mapping, _ = self.resolve_event_mapping(
                        event,
                        activity=activity,
                        track_name=track,
                        blacklist_rank=_safe_int(rank),
                        race_kind=(
                            "rival" if row.mapping_source == "rival_race" else "career"
                        ),
                        native_index=_safe_int(evidence.get("native_index", 0)),
                        native_count=_safe_int(evidence.get("native_count", 0)),
                    )
                    if mapping is not None and mapping.location_id == location:
                        self.reward_aliases[alias] = location
                        self.reward_alias_evidence[alias] = evidence
        except Exception as exc:
            self._session_state_loaded = True
            logger.warning(
                "Could not load seed-scoped client state %s: %s",
                path,
                exc,
            )

    def _save_state(self) -> bool:
        if not self._session_state_loaded:

            return False

        try:
            self.state_json_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            payload = {
                "schema": 8,
                "sms_pending": getattr(self, "sms_pending", {}),
                "sms_acknowledged": sorted(getattr(self, "sms_acknowledged", set())),
                "slot": self.slot_name,
                "seed_name": self.session_seed_name,
                "session_key": self.session_key,
                "delivered_received_indices": sorted(self.delivered_received_indices),
                "native_profile_seen": self.native_profile_seen,
                "queued_location_checks": sorted(self.queued_location_checks),
                "defeated_blacklist_ranks": sorted(self.defeated_blacklist_ranks),
                "blacklist_defeat_proofs": getattr(self, "blacklist_defeat_proofs", {}),
                "final_escape_proof": getattr(self, "final_escape_proof", {}),
                "deathlink_seen": sorted(getattr(self, "deathlink_seen", set())),
                "deathlink_bust_seen": sorted(
                    getattr(self, "deathlink_bust_seen", set())
                ),
                "deathlink_pending": getattr(self, "deathlink_pending", {}),
                "deathlink_claims": getattr(self, "deathlink_claims", {}),
                "reward_catalog": getattr(self, "reward_catalog", {}),
                "shop_catalog": getattr(self, "shop_catalog", {}),
                "seen_locations": sorted(getattr(self, "seen_locations", set())),
                "revealed_hint_locations": sorted(
                    getattr(self, "revealed_hint_locations", set())
                ),
                "manual_hint_locations": sorted(
                    getattr(self, "manual_hint_locations", set())
                ),
                "reward_alias_version": 4,
                "reward_alias_evidence": getattr(self, "reward_alias_evidence", {}),
                "reward_aliases": getattr(self, "reward_aliases", {}),
                "won_race_locations": sorted(
                    getattr(self, "won_race_locations", set())
                ),
            }

            tmp = self.state_json_path.with_suffix(".json.tmp")

            serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            saved_path = str(self.state_json_path)
            if (
                getattr(self, "_last_saved_state", None) == (saved_path, serialized)
                and self.state_json_path.is_file()
            ):
                return True
            tmp.write_text(serialized, encoding="utf-8")
            tmp.replace(self.state_json_path)
            self._last_saved_state = (saved_path, serialized)
            return True
        except Exception as exc:
            logger.warning(
                "Could not save seed-scoped client state: %s",
                exc,
            )
            return False

    @staticmethod
    def _safe_session_component(value: str) -> str:
        value = value.strip() or "unknown"
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
        cleaned = cleaned.strip("._-")
        return cleaned[:80] or "unknown"

    def configure_isolated_ap_session(self) -> None:

        seed_name = getattr(self, "server_seed_name", None)
        if not isinstance(seed_name, str) or not seed_name.strip():
            raise RuntimeError(
                "The server did not provide a seed name in RoomInfo. "
                "Reconnect to the actual AP server address; no Career save was opened."
            )

        if self.expected_seed_name and seed_name != self.expected_seed_name:
            raise RuntimeError(
                "Connected server seed does not match the requested seed. "
                f"Requested={self.expected_seed_name!r}, server={seed_name!r}. "
                "NFSMW will not be launched, so the wrong Career save cannot be opened."
            )

        profile_filename(self.slot_name)
        key, identity = session_save_identity(
            self.requested_server or getattr(self, "server_address", ""),
            seed_name,
            self.slot_name,
            int(getattr(self, "team", 0) or 0),
        )
        self.save_base_root = self.save_base_root.expanduser().resolve()
        requested_key = key
        key, identity, root = select_session(self.save_base_root, key, identity)
        if key != requested_key:
            logger.info(
                "AP SAVE RESUME: reusing the existing seed/team/slot save across a server address change: %s",
                root,
            )
        running = (
            self.game_process is not None
            and callable(getattr(self.game_process, "poll", None))
            and self.game_process.poll() is None
        )
        if (
            self.session_key
            and self.session_key != key
            and (self.game_writers or running)
        ):
            raise RuntimeError(
                "Close NFSMW before connecting this client to a different server or seed."
            )
        self.save_base_root = self.save_base_root.expanduser().resolve()
        validate_session_save_root(self.save_base_root, root, identity)
        self.session_seed_name = seed_name
        self.session_key = key
        self.session_identity = identity
        self.ap_documents_root = root

        self.state_json_path = self.ap_documents_root / "NFSMW_AP_ClientState.json"
        self._load_state()

        save_root = self.ap_documents_root / "NFS Most Wanted"

        self.current_blacklist_rank, self.current_save_path = (
            probe_current_blacklist_rank([save_root])
        )

        logger.info(
            "AP SESSION ISOLATION V2: server=%s seed=%s slot=%s",
            identity["server"],
            seed_name,
            self.slot_name,
        )
        logger.info(
            "AP SESSION ISOLATION: unique Documents root=%s",
            self.ap_documents_root,
        )
        logger.info(
            "AP SESSION ISOLATION: NFSMW save directory=%s",
            save_root,
        )
        logger.info(
            "Vanilla NFSMW save folders are NOT used for this "
            "Archipelago-launched session."
        )

    async def ensure_game_launched(self) -> None:
        if not self.auto_launch_game:
            logger.info("AP game auto-launch is disabled by NFSMW_AP_Client.ini.")
            return

        await asyncio.sleep(0.03)

        if self.in_game_connect and self.exit_event.is_set():
            return

        if self.game_ready_pids and self.game_process is None:
            logger.info(
                "NFSMW is already connected to the local bridge; "
                "auto-launch skipped."
            )
            return

        if self.game_process is not None:
            if self.game_process.poll() is None:
                screen = self.connection_screen
                if screen is not None and not screen.closed:
                    hide = getattr(screen, "hide_during_game_launch", None)
                    if callable(hide):
                        hide()
                await self.wait_for_game_bridge()
                return

        if self.ap_documents_root is None:
            raise RuntimeError(
                "Cannot launch NFSMW: AP isolated save root is not configured."
            )

        validate_session_save_root(
            self.save_base_root, self.ap_documents_root, self.session_identity
        )

        game_exe = self.game_exe.expanduser()

        if not game_exe.is_file():
            raise RuntimeError("GameExe does not exist: " + str(game_exe))

        if self.in_game_connect and (
            self.session_rejected or not self.ap_connected() or self.exit_event.is_set()
        ):
            logger.warning(
                "Career launch waiting for an authenticated Archipelago connection."
            )
            return

        cleanup = await asyncio.to_thread(cleanup_retired_assets, game_exe.parent)
        if cleanup["errors"] or cleanup["skipped_links"]:
            raise RuntimeError(
                "Old mod files could not be removed. Close the game and run NFSMW Setup again before launching."
            )
        environment = disabled_environment(os.environ)
        environment.pop("NFSMW_AP_SETUP", None)
        environment.pop("NFSMW_AP_SETUP_TOKEN", None)
        environment["NFSMW_AP_DOCUMENTS_ROOT"] = str(self.ap_documents_root)
        environment["NFSMW_AP_SEED_NAME"] = self.session_seed_name
        environment["NFSMW_AP_SLOT_NAME"] = self.slot_name
        environment["NFSMW_AP_SESSION_KEY"] = self.session_key
        environment["NFSMW_AP_ISOLATION_VERSION"] = "2"
        environment["NFSMW_AP_BOOTSTRAP"] = (
            "2" if self.slot_data.get("dealership_first_start") else "0"
        )

        slot = profile_filename(self.slot_name)
        has_profile = startup_has_profile(
            self.ap_documents_root,
            slot,
            bool(
                self.native_profile_seen
                or self.delivered_received_indices
                or self.won_race_locations
                or self.defeated_blacklist_ranks
                or self.queued_location_checks
            ),
        )
        environment["NFSMW_AP_FRESH_START"] = "0" if has_profile else "1"
        if has_profile and not self.native_profile_seen:
            self.native_profile_seen = True
            self._save_state()
        try:
            environment["NFSMW_AP_PREFERENCES_PATH"] = str(
                prepare_player_preferences(self.save_base_root, self.ap_documents_root)
            )
        except OSError as exc:
            logger.warning("Player settings could not be shared: %s", exc)
        logger.info(
            "AP SLOT STARTUP: %s",
            (
                "load existing native slot save"
                if has_profile
                else "create new native slot save"
            ),
        )

        from NFSMW_Wine import game_command

        launch_command, environment = await asyncio.to_thread(
            game_command, game_exe, self.ap_documents_root, environment
        )
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )

        try:
            log_path = game_exe.parent / "NFSMWArchipelago.log"
            self.game_log_before_launch = (
                (log_path.stat().st_mtime_ns, log_path.stat().st_size)
                if log_path.is_file()
                else None
            )
            self.game_process = subprocess.Popen(
                launch_command,
                cwd=str(game_exe.parent),
                env=environment,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise RuntimeError(
                "Could not start isolated speed.exe: " + str(exc)
            ) from exc

        if self.game_process.poll() is None:
            screen = self.connection_screen
            if screen is not None and not screen.closed:
                hide = getattr(screen, "hide_during_game_launch", None)
                if callable(hide):
                    hide()
        logger.info(
            "CREATED ISOLATED NFSMW PROCESS: %s (PID %d); waiting for its native AP bridge.",
            game_exe,
            self.game_process.pid,
        )
        logger.info(
            "This speed.exe process has its own server+seed+team+slot save root: %s",
            self.ap_documents_root,
        )
        logger.info(
            "AP Career uses profile %s. New sessions skip the prologue and open the dealership; "
            "the native save system writes the slot-named profile.",
            self.slot_name,
        )
        await self.wait_for_game_bridge()

    def game_startup_error(self, reason: str) -> str:
        log_path = self.game_exe.parent / "NFSMWArchipelago.log"
        detail = ""
        try:
            stat = log_path.stat()
            if (stat.st_mtime_ns, stat.st_size) != self.game_log_before_launch:
                with log_path.open("rb") as stream:
                    stream.seek(max(0, stat.st_size - 16384))
                    lines = (
                        stream.read(16384)
                        .decode("utf-8", errors="replace")
                        .splitlines()
                    )
                logger.error(
                    "Native startup log (%s):\n%s", log_path, "\n".join(lines[-20:])
                )
                failures = [
                    line
                    for line in lines
                    if "AP STARTUP GUARD" in line or "AP STARTUP ABORTED" in line
                ]
                if failures:
                    detail = " " + failures[-1][:240]
            else:
                detail = " No new game log was written. Check that the ASI loader and required scripts are installed."
        except OSError:
            detail = " No new game log was written. Check that the ASI loader and required scripts are installed."
        return reason + detail + " Native log: " + str(log_path)

    async def wait_for_game_bridge(self, timeout: float = 30.0) -> None:
        process = self.game_process
        deadline = time.monotonic() + timeout
        while not self.exit_event.is_set():
            code = process.poll()
            if code is not None:
                self.game_ready_pids.discard(process.pid)
                self.game_process = None
                unsigned = code & 0xFFFFFFFF
                reason = (
                    f"speed.exe exited during startup (code {code}, 0x{unsigned:08X})."
                )
                if unsigned == 5:
                    reason += " Check the save-isolation guard."
                elif unsigned == 13:
                    reason += (
                        " The game executable failed a startup compatibility check."
                    )
                raise RuntimeError(self.game_startup_error(reason))
            if process.pid in self.game_ready_pids or (
                os.name != "nt" and self.game_ready_pids
            ):
                if (
                    getattr(self, "desktop_mode", False)
                    and getattr(self, "desktop_game_process", None) is None
                ):
                    self.desktop_game_process = process
                logger.info(
                    "ISOLATED NFSMW NATIVE BRIDGE READY: PID %d, build %s, session %s.",
                    process.pid,
                    NATIVE_BUILD,
                    self.session_key,
                )
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    self.game_startup_error(
                        "speed.exe is running but its native AP bridge did not connect within 30 seconds. "
                        "Retry waits for this same process; no duplicate game will be started."
                    )
                )
            await asyncio.sleep(0.1)

    def refresh_isolated_save_rank(
        self,
        *,
        force: bool = False,
    ) -> None:
        if (
            self.ap_documents_root is None
            or time.monotonic() - self._live_rank_observed_at < 5.0
        ):
            return

        now = time.monotonic()

        if (
            not force
            and self._last_rank_probe_monotonic != 0.0
            and now - self._last_rank_probe_monotonic < 2.0
        ):
            return

        self._last_rank_probe_monotonic = now

        save_root = self.ap_documents_root / "NFS Most Wanted"

        rank, path = probe_current_blacklist_rank([save_root])

        if rank is None:
            return

        if rank != self.current_blacklist_rank:
            logger.info(
                "AP isolated save rank changed: %s -> #%d (%s)",
                (
                    f"#{self.current_blacklist_rank}"
                    if self.current_blacklist_rank is not None
                    else "<unknown>"
                ),
                rank,
                path,
            )

        self.current_blacklist_rank = rank
        self.current_save_path = path

    def observe_career_context(self, message: dict[str, Any]) -> None:
        if message.get("career_mode") is not True or self.ap_documents_root is None:
            return
        rank = _safe_int(message.get("blacklist_rank", 0))
        if 1 <= rank <= 15:
            self.current_blacklist_rank = rank
            self._live_rank_observed_at = time.monotonic()
        name = str(message.get("profile_name", ""))
        self.current_profile_name = ""
        if name:
            try:
                self.current_profile_name = profile_filename(name)
            except ValueError:
                return
        defeated_mask = message.get("defeated_blacklist_mask")
        valid_mask = (
            type(defeated_mask) is int
            and 0 <= defeated_mask <= 0xFFFE
            and not (defeated_mask & 1)
        )
        if (
            (1 <= rank <= 15 or rank == 0 and valid_mask)
            and self.current_profile_name == self.slot_name
            and self._session_state_loaded
        ):
            key = (self.session_key, rank, defeated_mask if valid_mask else None)
            if self.__dict__.get("_native_progress_key") != key:
                self._native_progress_key = key
                asyncio.create_task(
                    self.recover_native_progress(
                        rank, defeated_mask if valid_mask else None
                    )
                )

    def sync_slot_save(self) -> Optional[Path]:

        if self.ap_documents_root is None or not self.current_profile_name:
            return None
        slot = profile_filename(self.slot_name)
        source_name = profile_filename(self.current_profile_name)
        if (
            getattr(self, "session_identity", {}).get("version") == 2
            and source_name != slot
        ):

            return None
        root = self.ap_documents_root / "NFS Most Wanted"
        target = root / slot
        if target.is_dir():
            target = target / slot

        candidates = [root / source_name, root / source_name / source_name]
        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            return None
        if source_name == slot:
            target = source
        for path in (source, target):
            if path.is_symlink() or path.parent.is_symlink() or root.is_symlink():
                raise ValueError(
                    "Refusing a linked profile path outside the isolated save directory."
                )
            path.resolve().relative_to(root.resolve())
        stat = source.stat()
        if not 0x4039 <= stat.st_size <= 1024 * 1024:
            return None
        signature = (str(source), stat.st_size, stat.st_mtime_ns)
        now = time.monotonic()
        if self._save_observation is None or self._save_observation[0] != signature:
            self._save_observation = (signature, now)
            return None
        if now - self._save_observation[1] < 1.0:
            return None
        data = source.read_bytes()
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            self._save_observation = None
            return None
        same_file = source == target or (target.is_file() and source.samefile(target))
        if not same_file:
            if target.exists() and (
                not target.is_file() or target.stat().st_mtime_ns > stat.st_mtime_ns
            ):
                return None
            digest = hashlib.sha256(data).hexdigest()
            if digest != self._slot_save_digest or not target.exists():
                import tempfile

                descriptor, temporary = tempfile.mkstemp(prefix="NFSMW_AP_", dir=root)
                temporary_path = Path(temporary)
                try:
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    os.utime(temporary_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                    temporary_path.replace(target)
                finally:
                    temporary_path.unlink(missing_ok=True)
                self._slot_save_digest = digest
        self.current_save_path = target
        if not self.native_profile_seen:
            self.native_profile_seen = True
            self._save_state()
        if not self._slot_save_announced:
            logger.info(
                "SLOT SAVE READY: %s (game-written profile; original preserved)", target
            )
            self._slot_save_announced = True
        return target

    def log_milestone_candidate(
        self,
        msg: dict[str, Any],
    ) -> None:
        photo = msg.get("event_name") == "PhotoTrapCompleted"
        row = (
            completed_photo_location(msg, self.milestone_locations)
            if photo
            else completed_milestone_location(msg, self.milestone_locations)
        )
        if (
            row is None
            or not self.enable_milestone_checks
            or (photo and not self.enable_photo_ticket_checks)
        ):
            return
        location_id = row.location_id
        if (
            location_id in self.checked_locations
            or location_id in self.pending_checks
            or location_id in self.queued_location_checks
            or location_id in self.milestone_trigger_scheduled
        ):
            return
        self.milestone_trigger_scheduled.add(location_id)
        asyncio.create_task(
            self.send_milestone_check(
                row,
                metric_name=(
                    "photo_camera_completed" if photo else "native_milestone_completed"
                ),
                value=_safe_float(msg.get("value_float"), 0.0),
            )
        )

    async def connection_notice(
        self, phase: str, message: str, first_car: str = ""
    ) -> None:
        self.connection_message = {
            "type": "connection_status",
            "phase": phase,
            "message": message,
            "first_car": first_car,
            "server": self.requested_server,
            "slot": self.slot_name,
            "seed": self.session_seed_name
            or getattr(self, "server_seed_name", "")
            or "",
        }
        await self.broadcast(self.connection_message)

    async def connect_from_game(self, message: dict[str, Any]) -> None:
        try:
            server = normalize_server_address(str(message.get("server", "")))
            slot = str(message.get("slot", "")).strip()
            if not server or not slot or len(server) > 240 or len(slot) > 240:
                raise ValueError("Enter a server address and the exact slot name.")
            if any(ord(c) < 32 for c in server + slot):
                raise ValueError("Server and slot cannot contain control characters.")
            profile_filename(slot)
            if self.session_key and (
                slot != self.slot_name or server != self.requested_server
            ):
                raise ValueError("Restart the client to join a different room or slot.")
            self.slot_name = slot
            self.requested_server = server
            self.password = str(message.get("password", "")) or None
            self.auth = slot
            self.expected_seed_name = str(message.get("seed", "")).strip()
            self.session_rejected = False
            if not self.session_key:
                self.server_seed_name = None
            if (
                self.expected_seed_name
                and self.session_seed_name
                and self.expected_seed_name != self.session_seed_name
            ):
                raise ValueError(
                    "This seed does not match the authenticated room. Leave Seed blank or enter its exact seed name."
                )
            self.game_launch_failed = False
            self._connection_attempt_started = asyncio.get_running_loop().time()
            if self.session_key and self.ap_connected():
                asyncio.create_task(self.refresh_setup_state())
                return
            await self.connection_notice("connecting", "Connecting to Archipelago...")
            task = getattr(self, "server_task", None)
            if task and not self.ap_connected():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.server_task = None
            await self.connect(server)
        except (ValueError, OSError) as exc:
            await self.connection_notice("error", str(exc))

    async def launch_connection_screen(self) -> None:

        if self.auto_launch_game:
            if not self.game_exe.is_file():
                raise RuntimeError(
                    "Game not found. Check the GameExe setting or install the client beside speed.exe."
                )
            asi = self.game_exe.parent / "scripts" / "NFSMWArchipelago.asi"
            markers = (
                b"NFSMW_AP_GOALS_V1",
                b"NFSMW_AP_FINAL_ESCAPE_V2",
                b"NFSMW_AP_OPTIONAL_SHOPS_V1",
                b"NFSMW_AP_STOCK_SHOPS_V2",
                b"NFSMW_AP_RANDOMIZED_CAREER_V5",
                b"NFSMW_AP_SHARED_PREFERENCES_V1",
                b"NFSMW_AP_SPAWN_HOOK_V2",
                b"NFSMW_AP_CRASH_REPORT_V2",
                b"NFSMW_AP_MILESTONE_COMPLETION_V1",
                b"NFSMW_AP_SAVE_SCREEN_V1",
                b"NFSMW_AP_RIVAL_SERIES_V1",
                b"NFSMW_AP_EVENT_PERMITS_V1",
                b"NFSMW_AP_EVENT_MENUS_V1",
                b"NFSMW_AP_BLACKLIST_ROSTER_V1",
                b"NFSMW_AP_SAVE_BOOT_FLOW_V5",
                b"NFSMW_AP_BOUNTY_EARNINGS_V2",
                b"NFSMW_AP_RUNTIME_ABI_V1",
                b"NFSMW_AP_RELEASE_OPTIONS_V1",
                b"NFSMW_AP_CONNECTION_UI_V7",
                b"NFSMW_AP_DEALERSHIP_START_V17",
                b"NFSMW_AP_DEATHLINK_PURSUIT_V8",
                b"NFSMW_AP_CASH_DELIVERY_V1",
                b"NFSMW_AP_NATIVE_REWARDS_V12",
                b"NFSMW_AP_NATIVE_RACE_IDENTITY_V1",
                b"NFSMW_AP_NATIVE_SMS_V8",
                b"NFSMW_AP_DEALERSHIP_BOOT_V23",
                b"NFSMW_AP_BACKROOM_VISUALS_V1",
                b"NFSMW_AP_TURBO_TRAP_V6",
                b"NFSMW_AP_BRAKE_TRAP_V2",
                b"NFSMW_AP_FLASH_BANG_TRAP_V1",
                b"NFSMW_AP_TRUCK_TRAP_V7",
                b"NFSMW_AP_SEED_OPTIONS_V1",
                b"NFSMW_AP_SPEEDBREAKER_TRAP_V1",
                b"NFSMW_AP_BACKROOM_CAR_SWAP_V4",
                b"NFSMW_AP_NATIVE_LOW_GLARE_V5",
                b"NFSMW_AP_BLACKLIST_NAMES_V3",
            )
            installed = asi.read_bytes() if asi.is_file() else b""
            missing = [
                marker.decode("ascii") for marker in markers if marker not in installed
            ]
            if missing:
                raise RuntimeError(
                    "The game scripts need updating: "
                    + ", ".join(missing)
                    + ". Reinstall the scripts included with this client."
                )
            if not (asi.parent / "NFSMW_TurboTrap.wav").is_file():
                raise RuntimeError(
                    "Turbo Trap audio is missing. Reinstall the required game scripts with NFSMW_Setup.exe."
                )
            if not (asi.parent / "NFSMW_FlashBangTrap.wav").is_file():
                raise RuntimeError(
                    "Flash Bang Trap audio is missing. Reinstall the required game scripts with NFSMW_Setup.exe."
                )
            if not (asi.parent / "NFSMW_TruckTrap.wav").is_file():
                raise RuntimeError(
                    "Truck Trap audio is missing. Reinstall the required game scripts with NFSMW_Setup.exe."
                )
        try:
            from NFSMW_ConnectionScreen import ConnectionScreen

            self.connection_screen = ConnectionScreen(self)
        except (ImportError, RuntimeError) as exc:
            if getattr(sys, "frozen", False):
                raise RuntimeError(
                    "The bundled connection screen could not open. Extract the complete standalone ZIP, "
                    "including NFSMWClient_Data. NFSMW was not started."
                ) from exc
            raise RuntimeError(
                "The connection screen requires tkinter support."
            ) from exc

    def first_dealer_entry(self) -> Optional[dict[str, Any]]:
        location = _safe_int(self.slot_data.get("first_car_location_id", 0))
        entry = self.shop_catalog.get(location)
        if not self.slot_data.get("dealership_first_start") or not entry:
            return None
        if (
            entry["location_type"] != "dealership"
            or entry["recipient_player"] != self.slot
            or entry["item_type"] != "car"
            or not entry.get("item_car")
            or entry["item_id"] != _safe_int(self.slot_data.get("first_car_item_id", 0))
            or entry["price"] != 0
        ):
            return None
        return entry

    async def buy_first_car(self) -> None:

        logger.info(
            "Ignoring connection-screen purchase; buy the guaranteed car in the dealership."
        )
        await self.refresh_setup_state()

    async def refresh_setup_state(self) -> None:
        if (
            not self.in_game_connect
            or self.setup_finishing
            or self.game_launch_failed
            or not self.ap_connected()
            or self.session_rejected
        ):
            return
        if not self.slot_data.get("dealership_first_start"):
            await self.connection_notice(
                "error",
                "This room uses an older world. Generate it with the updated nfsmw.apworld.",
            )
            return
        location = _safe_int(self.slot_data.get("first_car_location_id", 0))
        entry = self.first_dealer_entry()
        screen = self.connection_screen
        if self.exit_event.is_set() or (
            not getattr(self, "ap_launcher_ui", False)
            and (screen is None or screen.closed)
        ):
            return
        if entry:
            started = getattr(self, "_connection_attempt_started", 0.0)
            if started:
                logger.info(
                    "AP PERF FIRST CAR VERIFIED: elapsed_ms=%d",
                    int((asyncio.get_running_loop().time() - started) * 1000),
                )
            self.setup_finishing = True
            await self.connection_notice(
                "relaunch", "Connected. Loading your career..."
            )
            await self.finish_connection_screen()
            return
        if screen is not None or getattr(self, "ap_launcher_ui", False):
            if location in self.shop_catalog:
                await self.connection_notice(
                    "error",
                    "This room's first-car reward is not a free local car. Check its world version.",
                )
            elif (
                self.connection_message.get("message")
                != "Connected. Validating the guaranteed dealership stock..."
            ):
                await self.connection_notice(
                    "connecting",
                    "Connected. Validating the guaranteed dealership stock...",
                )

    async def finish_connection_screen(self) -> None:

        launch_error = ""
        try:
            await self.ensure_game_launched()
        except (OSError, ValueError, RuntimeError) as exc:
            logger.error("Career launch failed: %s", exc)
            launch_error = str(exc)
        if self.exit_event.is_set():
            return
        ready = (
            self.game_process is not None
            and self.game_process.poll() is None
            and self.game_process.pid in self.game_ready_pids
        )
        if not launch_error and (
            ready
            or (self.game_ready_pids and self.game_process is None)
            or not self.auto_launch_game
        ):
            if self.connection_screen is not None:
                self.connection_screen.close()
            await self.connection_notice(
                "connected", "Connected to Archipelago as " + self.slot_name
            )
        else:
            screen = self.connection_screen
            if screen is not None and not screen.closed:
                restore = getattr(screen, "show_after_game_launch_failure", None)
                if callable(restore):
                    restore()
            self.setup_finishing = False
            self.game_launch_failed = bool(launch_error)
            await self.connection_notice(
                "error",
                (
                    "Could not open isolated Career: " + launch_error
                    if launch_error
                    else "Could not launch Career. Check GameExe and retry; see the client log."
                ),
            )

    async def setup_status_watchdog(self) -> None:
        while not self.exit_event.is_set():
            connected = self.ap_connected() and not self.session_rejected
            self.report_ap_connection_state(connected)
            if not connected:
                self.pending_checks.clear()
            await self.broadcast(
                {
                    "type": "ap_status",
                    "connected": connected,
                    "queued_checks": len(
                        self.queued_location_checks | self.pending_checks
                    ),
                }
            )
            await self.replay_deathlink()
            await self.replay_sms()
            if connected:
                await self.flush_queued_location_checks()

                for recovery in (
                    self.sync_blacklist_goal,
                    self.scout_shop_locations,
                    self.flush_seen_hints,
                ):
                    if recovery == self.sync_blacklist_goal:
                        now = asyncio.get_running_loop().time()
                        if now < getattr(self, "_next_goal_recovery", 0):
                            continue
                        self._next_goal_recovery = now + 10.0
                    try:
                        await recovery()
                    except Exception as exc:
                        logger.warning("AP recovery will retry: %s", exc)
            if self.in_game_connect:
                if (
                    self.setup_game_process is not None
                    and not self.setup_ui_ready
                    and not self.setup_ui_warning
                    and time.monotonic() - self.setup_launched_at > 40.0
                ):
                    self.setup_ui_warning = True
                    logger.error(
                        "The ASI has not confirmed a drawn connection screen. Check NFSMWArchipelago.log "
                        "for the current build, connection input attached, and prompt drawn in Present."
                    )
                try:
                    self.sync_slot_save()
                except (OSError, ValueError) as exc:
                    logger.warning("Slot save sync waiting: %s", exc)
                if self.ap_connected():
                    await self.refresh_setup_state()
                    if (
                        self.setup_finishing
                        and self.session_key
                        and (
                            self.connection_screen is None
                            or self.connection_screen.closed
                        )
                        and self.connection_message.get("phase") != "connected"
                    ):
                        await self.connection_notice(
                            "connected", "Connected to Archipelago as " + self.slot_name
                        )
                elif self.setup_finishing and self.session_key:
                    if self.connection_message.get("phase") != "connecting":
                        await self.connection_notice(
                            "connecting",
                            "Disconnected from AP; reconnecting to the same room...",
                        )
                elif (
                    self.connection_message.get("phase") == "connecting"
                    and not self.server_task
                ):
                    await self.connection_notice(
                        "error",
                        "Could not connect. Check server, slot and password; Enter retries.",
                    )
            await asyncio.sleep(1.0)

    def report_ap_connection_state(self, connected: bool) -> None:
        previous = getattr(self, "_last_reported_ap_connection", None)
        self._last_reported_ap_connection = connected
        if previous is True and not connected:
            socket = getattr(getattr(self, "server", None), "socket", None)
            code = getattr(socket, "close_code", None)
            reason = str(getattr(socket, "close_reason", "") or "")[:200]
            logger.warning(
                "AP connection lost (close code=%s, reason=%s). Earned checks remain queued; awaiting reconnect.",
                code if code is not None else "unavailable",
                reason or "not supplied",
            )
        elif previous is False and connected:
            logger.info(
                "AP connection restored; resuming queued checks and item delivery."
            )

    def event_invalid_slot(self):
        asyncio.create_task(
            self.connection_notice(
                "error", "Invalid slot. Enter the exact slot name and retry."
            )
        )

    def event_invalid_game(self):
        asyncio.create_task(
            self.connection_notice(
                "error", "This slot belongs to another game. Choose the NFSMW slot."
            )
        )

    async def server_auth(self, password_requested: bool = False):
        self._ap_authenticated = False
        screen = self.connection_screen
        form_active = screen is not None and not screen.closed
        if form_active:
            if not self.slot_name and self.username:
                profile_filename(self.username)
                self.slot_name = self.username
            if not self.requested_server:
                self.requested_server = normalize_server_address(
                    self.server_address or ""
                )
        if getattr(self, "ap_launcher_ui", False) and not form_active:
            if password_requested and not self.password:
                self._password_prompt = True
                widget = getattr(self.ui, "textinput", None)
                if widget is not None:
                    widget.password = True
                try:
                    logger.info(
                        "Room password required. Enter it in the client input below."
                    )
                    self.password = await self.console_input()
                finally:
                    self._password_prompt = False
                    if widget is not None:
                        widget.password = False
            while not self.exit_event.is_set():
                await self.get_username()
                if self.exit_event.is_set():
                    return
                try:
                    profile_filename(self.auth or "")
                    break
                except ValueError as exc:
                    logger.warning("%s", exc)
                    self.auth = self.username = None
            if self.exit_event.is_set():
                return
            self.slot_name = self.auth
            if not self.requested_server:
                self.requested_server = normalize_server_address(
                    self.server_address or ""
                )
        if password_requested and not self.password:
            await self.connection_notice(
                "error", "This room requires a password. Enter it in the third field."
            )
            return
        if not self.slot_name:
            await self.connection_notice(
                "error", "Enter the exact slot name in the NFSMW connection screen."
            )
            return
        self.auth = self.slot_name
        logger.info(
            "RoomInfo received; sending Archipelago Connect packet for slot %s.",
            self.slot_name,
        )
        await self.send_connect()

    def make_gui(self):
        from NFSMW_AP_GUI import make_gui

        return make_gui()

    async def connect(self, address: Optional[str] = None) -> None:
        if getattr(self, "ap_launcher_ui", False) and address:
            address, name, password = launcher_connection_target(address)
            if name is not None:
                self.username = name
            if password is not None:
                self.password = password
        await super().connect(address)

    def ap_connected(self) -> bool:
        if not self._ap_authenticated or self.server is None or self.slot is None:
            return False
        try:
            return bool(self.server.socket.open and not self.server.socket.closed)
        except Exception:
            return False

    async def broadcast(self, payload: dict[str, Any]) -> None:

        if not self.game_writers:
            return
        line = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("utf-8")
        dead: list[asyncio.StreamWriter] = []
        for writer in list(self.game_writers):
            try:
                writer.write(line)
                await asyncio.wait_for(writer.drain(), timeout=2.0)
            except Exception:
                dead.append(writer)
        for writer in dead:
            self.game_writers.discard(writer)
            writer.close()

    def _slot_game(self, player: int) -> str:
        try:
            info = self.slot_info[player]
            game = getattr(info, "game", None)
            if game:
                return str(game)
        except Exception:
            pass
        return self.game if player == self.slot else "Unknown"

    def _player_name(self, player: int) -> str:
        try:
            return str(self.player_names[player])
        except Exception:
            return f"Player {player}"

    def _resolve_item_name(self, item_id: int, game: str) -> str:

        if game == self.game:
            meta = self.item_manifest.get(item_id)
            if meta and meta.category == "Tires":
                return meta.name

        try:
            name = str(self.item_names.lookup_in_game(item_id, game))
            if not name.startswith("Unknown item"):
                return name
        except Exception:
            pass
        try:
            name = str(self.item_names[game][item_id])
            if not name.startswith("Unknown item"):
                return name
        except Exception:
            pass
        if game == self.game and item_id in self.item_manifest:
            return self.item_manifest[item_id].name
        return f"Item ID {item_id}"

    def _resolve_location_name(self, location_id: int, game: str) -> str:
        try:
            return str(self.location_names.lookup_in_game(location_id, game))
        except Exception:
            pass
        try:
            return str(self.location_names[game][location_id])
        except Exception:
            pass
        if location_id in self.shop_locations:
            return self.shop_locations[location_id].location_name
        return f"Location {location_id}"

    def _write_shop_cache(self) -> None:
        try:
            rows = [self.shop_catalog[k] for k in sorted(self.shop_catalog)]
            tmp = SHOP_CACHE_JSON.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            tmp.replace(SHOP_CACHE_JSON)
        except Exception as exc:
            logger.warning("Could not write AP shop cache: %s", exc)

    async def subscribe_shared_hints(self) -> None:
        keys = [
            f"_read_hints_{self.team}_{slot}" for slot in self.slot_info if slot > 0
        ]
        self.stored_data_notification_keys.update(keys)
        for offset in range(0, len(keys), 128):
            batch = keys[offset : offset + 128]
            await self.send_msgs(
                [{"cmd": "Get", "keys": batch}, {"cmd": "SetNotify", "keys": batch}]
            )

    async def scout_shop_locations(self) -> None:
        if not self.shop_locations or not self.ap_connected():
            return
        ids = set(self.shop_locations)
        if self.slot_data.get("reveal_event_rewards", False):
            ids |= {m.location_id for m in self.event_map.values()} | {
                m.location_id for m in self.milestone_locations
            }
        if self.server_locations:
            ids.intersection_update(self.server_locations)
        now = asyncio.get_running_loop().time()
        retries = self.__dict__.setdefault("_scout_retry_at", {})
        cached = set(self.shop_catalog) | set(getattr(self, "reward_catalog", {}))
        ids = sorted(x for x in ids - cached if now >= retries.get(x, 0))
        if not ids:
            return
        logger.info(
            "Scouting %d missing native store/race/milestone rewards.", len(ids)
        )

        slot_data = getattr(self, "slot_data", {}) or {}
        first_car = _safe_int(slot_data.get("first_car_location_id", 0))
        if (
            getattr(self, "in_game_connect", False)
            and slot_data.get("dealership_first_start")
            and first_car in ids
        ):
            retries[first_car] = now + 10.0
            try:
                await self.send_msgs(
                    [
                        {
                            "cmd": "LocationScouts",
                            "locations": [first_car],
                            "create_as_hint": 0,
                        }
                    ]
                )
            except Exception as exc:
                logger.warning("First-car scout will retry: %s", exc)
                return
            ids.remove(first_car)

        for start in range(0, len(ids), 200):
            batch = ids[start : start + 200]
            for location in batch:
                retries[location] = now + 10.0
            try:
                await self.send_msgs(
                    [{"cmd": "LocationScouts", "locations": batch, "create_as_hint": 0}]
                )
            except Exception as exc:
                logger.warning("Reward scouts will retry: %s", exc)
                break

    async def flush_seen_hints(self) -> None:
        if not self.ap_connected():
            return
        now = asyncio.get_running_loop().time()
        retries = self.__dict__.setdefault("_hint_retry_at", {})
        confirmed = self.__dict__.setdefault("_hint_confirmed", set())
        pending = self.__dict__.setdefault("_hint_pending", set())
        manual = getattr(self, "manual_hint_locations", set())
        locations = sorted(
            x
            for x in manual
            if x in self.server_locations
            and x not in confirmed
            and now >= retries.get(x, 0)
        )
        for offset in range(0, len(locations), 200):
            batch = locations[offset : offset + 200]
            for location in batch:
                retries[location] = now + 60.0
            pending.update(batch)
            try:

                await self.send_msgs(
                    [{"cmd": "LocationScouts", "locations": batch, "create_as_hint": 2}]
                )
            except Exception as exc:
                pending.difference_update(batch)
                logger.warning("Requested hints retained for retry: %s", exc)
                break

    async def accept_location_preview(self, event: dict[str, Any]) -> bool:
        location = _safe_int(event.get("location_id", 0))
        event_id = str(event.get("event_id", ""))[:128]
        activity = str(event.get("activity", "")).strip()[:64]
        if (
            not self.slot_data.get("reveal_event_rewards", False)
            and location not in self.shop_locations
        ):
            return True
        if event_id:
            mapping, resolution = self.resolve_event_mapping(
                event_id,
                activity=activity,
                track_name=str(event.get("track_name", ""))[:192],
                blacklist_rank=_safe_int(event.get("blacklist_rank", 0)),
                race_kind=str(event.get("race_kind", "")),
                rival_stage=_safe_int(event.get("rival_stage", 0)),
                rival_stages=_safe_int(event.get("rival_stages", 0)),
                native_index=_safe_int(event.get("native_index", 0)),
                native_count=_safe_int(event.get("native_count", 0)),
            )
            if mapping is None:
                identity = (
                    event_id,
                    activity,
                    str(event.get("track_name", "")),
                    _safe_int(event.get("blacklist_rank", 0)),
                )
                now = asyncio.get_running_loop().time()
                warnings = self.__dict__.setdefault("_unmapped_preview_at", {})
                if now >= warnings.get(identity, 0):
                    warnings[identity] = now + 30.0
                    logger.warning(
                        "Reward preview unmapped: event=%s activity=%s track=%s rank=%s (%s)",
                        *identity,
                        resolution,
                    )
                return False
            location = mapping.location_id
            alias = "|".join(
                (
                    event_id,
                    activity.casefold(),
                    str(_safe_int(event.get("blacklist_rank", 0))),
                    str(event.get("track_name", "")),
                    str(_safe_int(event.get("native_index", 0))),
                )
            )
            self.__dict__.setdefault("reward_aliases", {})[alias] = location
            self.__dict__.setdefault("reward_alias_evidence", {})[alias] = {
                k: event[k]
                for k in (
                    "race_kind",
                    "rival_stage",
                    "rival_stages",
                    "native_index",
                    "native_count",
                )
                if k in event
            }
            bindings = self.__dict__.setdefault("_announced_race_bindings", set())
            if alias not in bindings:
                bindings.add(alias)
                logger.info(
                    "NATIVE RACE BIND: event=%s rank=%s track=%s -> %s (%s)",
                    event_id,
                    event.get("blacklist_rank", 0),
                    event.get("track_name", ""),
                    mapping.location_name,
                    resolution,
                )
        if not location and event.get("category"):
            rank = _safe_int(event.get("blacklist_rank", 0))
            try:
                threshold = float(event.get("threshold", "nan"))
            except (TypeError, ValueError):
                return False
            matches = [
                row.location_id
                for row in self.milestone_locations
                if row.blacklist_rank == rank
                and row.category == event.get("category")
                and abs(float(milestone_target(row)[1]) - threshold) < 0.01
            ]
            if len(matches) != 1:
                return False
            location = matches[0]
        known = (
            set(self.shop_locations)
            | {m.location_id for m in self.event_map.values()}
            | {m.location_id for m in self.milestone_locations}
        )
        if location not in known or (
            self.server_locations and location not in self.server_locations
        ):
            return False
        seen = self.__dict__.setdefault("seen_locations", set())
        seen.add(location)
        if not self._save_state():
            return False

        cached = getattr(self, "reward_catalog", {}).get(location)
        if cached:
            await self.broadcast(
                {
                    "type": "reward_slot",
                    **cached,
                    "observed_event_id": event_id,
                    "observed_activity": activity,
                    "observed_rank": _safe_int(event.get("blacklist_rank", 0)),
                    "observed_track": str(event.get("track_name", "")),
                    "observed_index": _safe_int(event.get("native_index", 0)),
                }
            )
        elif (
            self.ap_connected()
            and location in self.server_locations
            and location not in self.shop_locations
        ):
            now = asyncio.get_running_loop().time()
            retries = self.__dict__.setdefault("_preview_scout_retry_at", {})
            if now >= retries.get(location, 0):
                retries[location] = now + 5.0
                await self.send_msgs(
                    [
                        {
                            "cmd": "LocationScouts",
                            "locations": [location],
                            "create_as_hint": 0,
                        }
                    ]
                )
                logger.info(
                    "Requested missing reward scout for %s (%s): %d",
                    event_id,
                    activity,
                    location,
                )
        return True

    async def accept_game_journal(self, msg: dict[str, Any]) -> None:
        if (
            not self._session_state_loaded
            or not self.session_key
            or msg.get("session_key") != self.session_key
        ):
            return
        key = str(msg.get("event_key", ""))
        payload = msg.get("payload", "")
        if (
            not key
            or len(key) > 256
            or not isinstance(payload, str)
            or len(payload) > 16384
        ):
            return
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "final_escape_complete":
            if (
                event.get("career_mode") is not True
                or event.get("profile_name") != self.slot_name
                or event.get("source") != "native_final_escape"
                or event.get("epic_pursuit") is not True
                or event.get("evaded") is not True
            ):
                return
            proof = {
                "version": 2,
                "session": self.session_key,
                "source": "native_final_escape",
                "epic_pursuit": True,
                "evaded": True,
                "event_id": event.get("event_id"),
                "defeated_blacklist_mask": event.get("defeated_blacklist_mask"),
            }
            if not final_escape_verified(proof, self.session_key, self.slot_data):
                return
            if not await self.recover_native_progress(
                0, proof["defeated_blacklist_mask"]
            ):
                return
            previous = getattr(self, "final_escape_proof", {})
            self.final_escape_proof = proof
            if not self._save_state():
                self.final_escape_proof = previous
                return
            accepted = True
            await self.sync_blacklist_goal()
        elif event.get("type") == "career_complete":
            if (
                event.get("career_mode") is not True
                or event.get("profile_name") != self.slot_name
            ):
                return
            await self.recover_native_progress(0)
            accepted = True
        elif event.get("type") == "location_preview":
            accepted = await self.accept_location_preview(event)
        elif event.get("type") == "blacklist_unlocked":
            rank = _safe_int(event.get("blacklist_rank"))
            if (
                event.get("race_kind") != "rival"
                or _safe_int(event.get("rival_rank")) != rank
            ):
                return
            accepted = await self.send_blacklist_unlocked_check(rank)
        elif (
            event.get("type") == "race_result"
            and event.get("won") is True
            and _safe_int(event.get("ranking")) == 1
        ):
            event_id = str(event.get("event_id", ""))[:128]
            rival_rank = _safe_int(event.get("rival_rank", 0))
            evidence = dict(
                activity=str(event.get("activity", "")),
                track_name=str(event.get("track_name", "")),
                blacklist_rank=_safe_int(event.get("blacklist_rank", 0)),
                race_kind=str(event.get("race_kind", "")),
                rival_stage=_safe_int(event.get("rival_stage", 0)),
                rival_stages=_safe_int(event.get("rival_stages", 0)),
                native_index=_safe_int(event.get("native_index", 0)),
                native_count=_safe_int(event.get("native_count", 0)),
            )
            mapping, _ = self.resolve_event_mapping(event_id, rival_rank, **evidence)
            if mapping is None:
                return
            await self.check_race_result(event_id, 1, True, rival_rank, **evidence)
            accepted = (
                mapping.location_id in self.checked_locations
                or mapping.location_id in self.queued_location_checks
            )
        else:
            return
        if accepted and self._save_state():
            await self.broadcast(
                {
                    "type": "game_journal_ack",
                    "event_key": key,
                    "session_key": self.session_key,
                }
            )
            await self.flush_seen_hints()

    async def process_location_info(self, locations: list[Any]) -> None:
        changed = 0
        previous_shop_count = len(self.shop_catalog)
        rewards_changed = False
        from NFSMW_ClientView import blacklist_locations

        event_locations = blacklist_locations(self)
        race_by_location = {m.location_id: m for m in self.event_map.values()}
        milestone_by_location = {m.location_id: m for m in self.milestone_locations}
        for item in locations:
            location_id = _safe_int(getattr(item, "location", 0))
            if (
                location_id not in self.shop_locations
                and location_id not in race_by_location
                and location_id not in milestone_by_location
                and location_id not in event_locations
            ):
                continue
            if location_id in getattr(self, "_hint_pending", set()):
                self._hint_pending.discard(location_id)
                self.__dict__.setdefault("_hint_confirmed", set()).add(location_id)

            recipient = _safe_int(getattr(item, "player", 0))
            item_id = _safe_int(getattr(item, "item", 0))
            flags = _safe_int(getattr(item, "flags", 0))
            recipient_game = self._slot_game(recipient)
            recipient_name = self._player_name(recipient)
            item_name = self._resolve_item_name(item_id, recipient_game)
            if location_id in event_locations and location_id in getattr(
                self, "manual_hint_locations", set()
            ):
                self.__dict__.setdefault("event_hint_catalog", {})[location_id] = {
                    "item_name": item_name,
                    "recipient_name": recipient_name,
                }
            if location_id not in self.shop_locations:
                if not self.slot_data.get("reveal_event_rewards", False):
                    continue
                race = race_by_location.get(location_id)
                milestone = milestone_by_location.get(location_id)
                target = milestone_target(milestone)[1] if milestone else None
                if not race and target is None:
                    continue
                entry = {
                    "location_id": location_id,
                    "location_type": "race" if race else "milestone",
                    "location_name": (
                        race.location_name if race else milestone.location_name
                    ),
                    "event_id": race.event_id if race else "",
                    "blacklist_rank": (
                        int(race.event_id.split(".")[0])
                        if race
                        else milestone.blacklist_rank
                    ),
                    "category": milestone.category if milestone else "",
                    "threshold": str(target) if milestone else "",
                    "item_id": item_id,
                    "item_name": item_name,
                    "recipient_name": recipient_name,
                    "recipient_player": recipient,
                    "recipient_game": recipient_game,
                    "checked": location_id in self.checked_locations,
                    "session_key": self.session_key,
                }
                entry["check_status"] = self._reward_check_status(
                    location_id, entry["blacklist_rank"]
                )
                if self.reward_catalog.get(location_id) == entry:

                    continue
                self.reward_catalog[location_id] = entry
                await self.broadcast({"type": "reward_slot", **entry})
                for alias, target in getattr(self, "reward_aliases", {}).items():
                    if target == location_id:
                        await self.broadcast(
                            {
                                "type": "reward_slot",
                                **entry,
                                "observed_event_id": alias.split("|", 1)[0],
                                "observed_activity": (
                                    alias.split("|", 4)[1] if "|" in alias else ""
                                ),
                                "observed_rank": (
                                    _safe_int(alias.split("|", 4)[2])
                                    if alias.count("|") >= 2
                                    else 0
                                ),
                                "observed_track": (
                                    alias.split("|", 4)[3]
                                    if alias.count("|") >= 3
                                    else ""
                                ),
                                "observed_index": (
                                    _safe_int(alias.split("|", 4)[4])
                                    if alias.count("|") >= 4
                                    else 0
                                ),
                            }
                        )
                rewards_changed = True
                continue
            meta = self.shop_locations[location_id]
            item_meta = (
                self.item_manifest.get(item_id) if recipient_game == self.game else None
            )
            multiplier = float(self.slot_data.get("shop_price_multiplier", 1.0) or 1.0)
            price = max(0, int(round(meta.base_price * multiplier)))
            price = cash_price(
                price, item_id, item_meta.item_type if item_meta else "", item_name
            )
            if (
                self.slot_data.get("dealership_first_start")
                and location_id
                == _safe_int(self.slot_data.get("first_car_location_id", 0))
                and recipient == self.slot
                and item_meta
                and item_meta.item_type == "car"
                and item_id == _safe_int(self.slot_data.get("first_car_item_id", 0))
            ):
                price = 0

            entry = {
                "location_id": location_id,
                "location_type": meta.location_type,
                "location_name": meta.location_name,
                "car": meta.car,
                "category": meta.category,
                "tier": meta.tier,
                "price": price,
                "item_id": item_id,
                "item_name": item_name,
                "item_type": item_meta.item_type if item_meta else "remote",
                "item_car": item_meta.car if item_meta else "",
                "item_category": item_meta.category if item_meta else "",
                "item_tier": item_meta.tier if item_meta else "",
                "recipient_player": recipient,
                "recipient_name": recipient_name,
                "recipient_game": recipient_game,
                "recipient_is_local": recipient == self.slot,
                "flags": flags,
                "checked": location_id in self.checked_locations,
            }
            if self.shop_catalog.get(location_id) == entry:
                continue
            self.shop_catalog[location_id] = entry
            changed += 1
            await self.broadcast({"type": "shop_slot", **entry})

        if changed:
            self._write_shop_cache()
        count = len(self.shop_catalog)
        if count > max(
            previous_shop_count, getattr(self, "_shop_catalog_reported_count", 0)
        ):
            self._shop_catalog_reported_count = count
            logger.info(
                "AP shop catalog: %d/%d locations scouted.",
                count,
                len(self.shop_locations),
            )
        if rewards_changed or changed:
            self._save_state()
        if rewards_changed or changed:
            await self.refresh_setup_state()

    def _blacklist_player_names(self, include_cross: bool = False) -> Dict[int, str]:
        defaults = (
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
        if include_cross:
            defaults += ("Cross",)
        names = {}
        for player in sorted(
            slot for slot in self.player_names if isinstance(slot, int)
        ):
            if player <= 0 or player == self.slot:
                continue
            info = self.slot_info.get(player)
            kind = getattr(info, "type", None)
            if getattr(kind, "value", kind) == 2:
                continue
            name = str(getattr(info, "name", None) or self.player_names[player]).strip()
            name = "".join(c for c in name if c.isprintable()).strip()
            if not name:
                continue
            names[15 - len(names)] = name
            if len(names) == len(defaults):
                break
        return {15 - i: names.get(15 - i, name) for i, name in enumerate(defaults)}

    async def replay_seed_config(self) -> None:
        await self.replay_deathlink()
        if not self.slot_data:
            return

        starting_car = (
            ""
            if self.slot_data.get("dealership_first_start")
            else str(self.slot_data.get("starting_car", ""))
        )
        randomize_opponents = bool(
            self.slot_data.get(
                "randomize_opponent_cars",
                False,
            )
        )
        opponent_seed = _safe_int(
            self.slot_data.get(
                "opponent_car_seed",
                0,
            )
        )
        starting_car_price = max(
            0,
            _safe_int(
                self.slot_data.get("starting_car_price", 5000),
                5000,
            ),
        )

        await self.broadcast(
            {
                "type": "seed_config",
                **bounty_settings(self.slot_data),
                **{
                    "blacklist_name_" + str(rank): name
                    for rank, name in self._blacklist_player_names().items()
                },
                "cross_name": self._blacklist_player_names(include_cross=True)[0],
                "traps_enabled": self.traps_enabled(),
                "goal": goal_settings(self.slot_data)["goal"],
                "blacklist_exist_count": blacklist_exist_count(self.slot_data),
                "shuffle_performance_parts": bool(
                    self.slot_data.get("shuffle_performance_parts", False)
                ),
                "visual_store_checks": bool(
                    self.slot_data.get("visual_store_checks", False)
                ),
                "reveal_event_rewards": bool(
                    self.slot_data.get("reveal_event_rewards", False)
                ),
                "randomize_blacklist_unlocks": bool(
                    self.slot_data.get("randomize_blacklist_unlocks", False)
                ),
                "blacklist_event_permits": event_permit_mode(self.slot_data),
                "blacklist_event_mask": event_permit_mask(
                    self.slot_data, self.items_received
                ),
                "starting_car": starting_car,
                "randomize_opponent_cars": randomize_opponents,
                "opponent_car_seed": opponent_seed,
                "randomize_blacklist_appearance": bool(
                    self.slot_data.get("randomize_blacklist_appearance", False)
                ),
                "blacklist_appearance_seed": _safe_int(
                    self.slot_data.get("blacklist_appearance_seed", opponent_seed)
                ),
                "starting_car_price": starting_car_price,
                "dealership_first_start": bool(
                    self.slot_data.get("dealership_first_start", False)
                ),
            }
        )

        blacklist = (
            self.slot_data.get(
                "blacklist_cars",
                {},
            )
            or {}
        )

        sent = 0

        for raw_rank, car in blacklist.items():
            rank = _safe_int(raw_rank)

            if not (1 <= rank <= 15):
                continue

            await self.broadcast(
                {
                    "type": "blacklist_car_config",
                    "rank": rank,
                    "car": str(car),
                }
            )
            sent += 1

        logger.info(
            "Sent randomized seed car config to NFSMW: "
            "starting_car=%s, blacklist_cars=%d, opponent_seed=%d.",
            starting_car or "<missing>",
            sent,
            opponent_seed,
        )

    async def replay_shop_catalog(self) -> None:
        for location_id in sorted(self.shop_catalog):
            entry = dict(self.shop_catalog[location_id])
            entry["checked"] = location_id in self.checked_locations
            if "price" in entry:
                entry["price"] = cash_price(
                    _safe_int(entry["price"]),
                    _safe_int(entry.get("item_id")),
                    entry.get("item_type", ""),
                    entry.get("item_name", ""),
                )
                self.shop_catalog[location_id]["price"] = entry["price"]
            if entry.get("recipient_game") == self.game:
                meta = getattr(self, "item_manifest", {}).get(entry.get("item_id"))
                if meta and meta.category == "Tires":
                    entry["item_name"] = meta.name
            await self.broadcast({"type": "shop_slot", **entry})
        for location_id, cached in sorted(getattr(self, "reward_catalog", {}).items()):
            if not self.slot_data.get("reveal_event_rewards", False):
                continue
            entry = dict(cached)
            entry["checked"] = location_id in self.checked_locations
            if entry.get("recipient_game") == self.game:
                meta = getattr(self, "item_manifest", {}).get(entry.get("item_id"))
                if meta and meta.category == "Tires":
                    entry["item_name"] = meta.name
            entry["check_status"] = self._reward_check_status(
                location_id, _safe_int(entry.get("blacklist_rank", 0))
            )
            await self.broadcast({"type": "reward_slot", **entry})
            for alias, target in getattr(self, "reward_aliases", {}).items():
                if target == location_id:
                    await self.broadcast(
                        {
                            "type": "reward_slot",
                            **entry,
                            "observed_event_id": alias.split("|", 1)[0],
                            "observed_activity": (
                                alias.split("|", 4)[1] if "|" in alias else ""
                            ),
                            "observed_rank": (
                                _safe_int(alias.split("|", 4)[2])
                                if alias.count("|") >= 2
                                else 0
                            ),
                            "observed_track": (
                                alias.split("|", 4)[3] if alias.count("|") >= 3 else ""
                            ),
                            "observed_index": (
                                _safe_int(alias.split("|", 4)[4])
                                if alias.count("|") >= 4
                                else 0
                            ),
                        }
                    )

    def traps_enabled(self) -> bool:
        return trap_allowed(self.slot_data)

    def filter_received_payload(self, payload, pending):
        return retired_item_payload(
            payload, trap_allowed(self.slot_data, payload.get("item_id")), pending
        )

    def has_blacklist_unlock(self, rank):
        return any(
            _safe_int(getattr(item, "item", 0)) == 1300000 + rank
            for item in self.items_received
        )

    def has_event_permit(self, rank):
        return events_available(self.slot_data, self.items_received, rank)

    async def replay_blacklist_unlock_checks(self):
        if not self.slot_data.get("randomize_blacklist_unlocks", False):
            return
        for rank in range(1, 16):
            if self.has_blacklist_unlock(rank):
                await self.send_blacklist_unlocked_check(rank)

    async def replay_received_inventory(self) -> None:
        await self.replay_blacklist_unlock_checks()

        for index in sorted(self.known_received):
            payload = dict(self.known_received[index])
            meta = getattr(self, "item_manifest", {}).get(payload.get("item_id"))
            if meta and meta.category == "Tires":
                payload["item_name"], payload["category"] = meta.name, meta.category
            payload["session_key"] = self.session_key
            payload["notify"] = index in self.pending_received
            payload = self.filter_received_payload(
                payload, index in self.pending_received
            )
            await self.broadcast(payload)

    def acknowledge_received_item(self, msg: dict[str, Any]) -> bool:
        index = _safe_int(msg.get("index", -1), -1)
        item = self.known_received.get(index)
        if item is None:
            return False
        item = retired_item_payload(item, False, False)
        if item.get("item_type") == "cash" and (
            msg.get("cash_credited") is not True
            or msg.get("session_key") != self.session_key
            or _safe_int(msg.get("item_id", 0)) != item.get("item_id")
        ):
            logger.warning(
                "Ignoring cash ACK without a native credit receipt: %d", index
            )
            return False
        if item.get("item_type") == "trap" and (
            msg.get("trap_consumed") is not True
            or msg.get("session_key") != self.session_key
            or _safe_int(msg.get("item_id", 0)) != item.get("item_id")
        ):
            logger.warning(
                "Ignoring trap ACK without a native consumption receipt: %d", index
            )
            return False
        pending = self.pending_received.pop(index, None)
        existed = index in self.delivered_received_indices
        self.delivered_received_indices.add(index)
        if not self._save_state():
            if not existed:
                self.delivered_received_indices.discard(index)
            if pending is not None:
                self.pending_received[index] = pending
            return False
        return True

    async def send_location_check(
        self,
        location_id: int,
        *,
        source: str,
        durable: bool = True,
    ) -> tuple[bool, str]:
        if location_id in self.checked_locations:
            return False, "already_checked"
        if location_id in self.pending_checks:
            return False, "already_pending"
        rank = self.event_location_ranks.get(location_id)
        if rank and not self.has_event_permit(rank):
            return False, "event_permit_required"
        if location_id in self.queued_location_checks:
            return False, "already_queued"

        if self.server_locations and location_id not in self.server_locations:
            logger.error(
                "Refusing LocationCheck %d because it is not present "
                "in this AP seed (%s).",
                location_id,
                source,
            )
            return False, "not_in_seed"

        if durable:
            self.queued_location_checks.add(location_id)
            self._save_state()
        if not self.ap_connected():
            if not durable:
                return False, "shop_requires_ap_connection"
            logger.warning(
                "LocationCheck queued until Archipelago authentication completes: %d (%s).",
                location_id,
                source,
            )
            return False, "queued_until_ap_connected"

        self.pending_checks.add(location_id)
        retries = self.__dict__.setdefault("_check_retry_at", {})
        retries[location_id] = asyncio.get_running_loop().time() + 10.0
        try:
            await self.send_msgs(
                [
                    {
                        "cmd": "LocationChecks",
                        "locations": [location_id],
                    }
                ]
            )
            if not self.ap_connected():
                raise ConnectionError("AP disconnected during check transmission")

            if not durable:
                self.queued_location_checks.add(location_id)
                self._save_state()
            logger.info(
                "LocationCheck sent, awaiting server confirmation: %d (%s).",
                location_id,
                source,
            )
            return True, "sent"
        except Exception:
            self.pending_checks.discard(location_id)
            retries.pop(location_id, None)
            if not durable:
                return False, "ap_send_failed"
            logger.warning(
                "LocationCheck %d retained for reconnect after a failed send.",
                location_id,
            )
            return False, "queued_until_ap_connected"

    def reconcile_location_checks(self) -> None:
        self.pending_checks.difference_update(self.checked_locations)
        self.queued_location_checks.difference_update(self.checked_locations)
        self._save_state()

    async def flush_queued_location_checks(self) -> None:
        if not self.ap_connected() or not self.queued_location_checks:
            return

        changed = False
        now = asyncio.get_running_loop().time()
        retries = self.__dict__.setdefault("_check_retry_at", {})
        for location in list(self.pending_checks):
            if now >= retries.setdefault(location, now + 10.0):
                self.pending_checks.discard(location)

        for location_id in sorted(list(self.queued_location_checks)):
            if location_id in self.checked_locations:
                self.queued_location_checks.discard(location_id)
                changed = True
                continue
            if location_id in self.pending_checks:
                continue
            rank = self.event_location_ranks.get(location_id)
            if rank and not self.has_event_permit(rank):
                continue

            if self.server_locations and location_id not in self.server_locations:
                logger.error(
                    "Queued LocationCheck %d is not present in this AP seed; keeping it queued.",
                    location_id,
                )
                continue

            self.pending_checks.add(location_id)
            retries[location_id] = now + 10.0
            try:
                await self.send_msgs(
                    [
                        {
                            "cmd": "LocationChecks",
                            "locations": [location_id],
                        }
                    ]
                )
            except Exception as exc:
                self.pending_checks.discard(location_id)
                logger.warning(
                    "Could not flush queued LocationCheck %d yet: %s",
                    location_id,
                    exc,
                )
                continue

            location_name = self._resolve_location_name(location_id, self.game)
            logger.info(
                "Queued LocationCheck sent after AP authentication: %d (%s).",
                location_id,
                location_name,
            )

            await self.broadcast(
                {
                    "type": "location_check_sent",
                    "location_id": location_id,
                    "location_name": location_name,
                    "source": "deferred_queue",
                }
            )

        if changed:
            self._save_state()

    async def accept_milestone_journal(self, msg: dict[str, Any]) -> None:
        if (
            not self._session_state_loaded
            or not self.session_key
            or msg.get("session_key") != self.session_key
            or not self.enable_milestone_checks
        ):
            return
        try:
            event = json.loads(str(msg.get("payload", "")))
        except (ValueError, TypeError):
            return
        location_id = _safe_int(msg.get("location_id", 0))
        row = next(
            (r for r in self.milestone_locations if r.location_id == location_id), None
        )
        if row is None or not isinstance(event, dict):
            return
        photo = row.category == "Photo Ticket"
        if photo and (
            not self.enable_photo_ticket_checks
            or completed_photo_location(event, self.milestone_locations) != row
        ):
            return
        completed = event.get("event_name") == "MilestoneCompleted"
        if (
            completed
            and completed_milestone_location(event, self.milestone_locations) != row
        ):
            return
        value = _safe_float(event.get("value_float"), float("nan"))
        reached = (
            event.get("event_name") == "MNotifyMilestoneReached" or photo or completed
        )
        cumulative = row.category in {
            "Trade Paint",
            "Bounty",
            "Cost to State",
            "Infractions",
            "Roadblock",
            "Spike Strip",
            "Pursuit Time",
        }
        if (
            event.get("career_mode") is not True
            or _safe_int(event.get("blacklist_rank", 0)) != row.blacklist_rank
            or event.get("ap_category") != row.category
            or not math.isfinite(value)
            or value < 0
            or event.get("event_name")
            not in (
                "MNotifyMilestoneReached",
                "MNotifyMilestoneProgress",
                "PhotoTrapCompleted",
                "MilestoneCompleted",
            )
            or (not reached and not cumulative)
            or (not completed and row.category == "Pursuit Evasion" and value <= 0)
            or (not completed and not metric_satisfies(row, value))
        ):
            return
        sent, reason = await self.send_location_check(
            location_id, source="persistent offline milestone / " + row.location_name
        )
        if reason in ("not_in_seed", "event_permit_required"):
            return

        if location_id in self.checked_locations or self._save_state():
            await self.broadcast(
                {
                    "type": "milestone_journal_ack",
                    "location_id": location_id,
                    "session_key": self.session_key,
                }
            )

    async def send_milestone_check(
        self,
        location: MilestoneLocation,
        *,
        metric_name: str,
        value: float,
    ) -> None:
        try:
            sent, reason = await self.send_location_check(
                location.location_id,
                source=(
                    f"milestone / rank #{location.blacklist_rank} / "
                    f"{location.category} / {metric_name}={value:.3f} / "
                    f"{location.location_name}"
                ),
            )

            await self.broadcast(
                {
                    "type": "milestone_check_ack",
                    "location_id": location.location_id,
                    "location_name": location.location_name,
                    "blacklist_rank": location.blacklist_rank,
                    "category": location.category,
                    "tier": location.tier,
                    "metric_name": metric_name,
                    "value": value,
                    "location_sent": sent,
                    "reason": reason,
                }
            )

            if sent:
                logger.info(
                    "LIVE MILESTONE CHECK SENT: %d (%s) "
                    "[rank #%d, metric=%s, value=%.3f].",
                    location.location_id,
                    location.location_name,
                    location.blacklist_rank,
                    metric_name,
                    value,
                )
            elif reason in (
                "already_checked",
                "already_pending",
                "already_queued",
            ):
                logger.debug(
                    "Milestone check suppressed (%s): %s",
                    reason,
                    location.location_name,
                )
            elif reason == "queued_until_ap_connected":
                logger.warning(
                    "LIVE MILESTONE CHECK QUEUED: %s",
                    location.location_name,
                )
            else:
                logger.warning(
                    "Milestone check not sent (%s): %s",
                    reason,
                    location.location_name,
                )
        finally:
            self.milestone_trigger_scheduled.discard(location.location_id)

    def _blacklist_rank_from_event(self, event_id: str) -> Optional[int]:
        match = re.match(r"^(\d+)\.", event_id.strip(), re.IGNORECASE)
        if not match:
            return None
        rank = int(match.group(1))
        return rank if 1 <= rank <= 15 else None

    def _next_unchecked_rival_mapping(self, rank: int) -> Optional[EventMapping]:
        rows = self.rival_mappings_by_rank.get(rank, [])
        for row in rows:
            if (
                row.location_id not in self.checked_locations
                and row.location_id not in self.pending_checks
                and row.location_id not in self.queued_location_checks
            ):
                return row
        return rows[-1] if rows else None

    def _find_blacklist_defeated_location(self, rank: int) -> tuple[int, str]:
        if not (1 <= rank <= 15) or not self.server_locations:
            return 0, ""

        canonical = 2600000 + (16 - rank) * 10 + 2
        if canonical in self.server_locations:
            return canonical, f"Blacklist #{rank} Defeated"
        rival = BLACKLIST_NAMES.get(rank, "")
        strong: list[tuple[int, str]] = []
        fallback: list[tuple[int, str]] = []

        for location_id in self.server_locations:
            try:
                name = self._resolve_location_name(location_id, self.game)
            except Exception:
                continue
            key = re.sub(r"[^A-Z0-9]+", " ", str(name).upper()).strip()
            compact = key.replace(" ", "")
            has_rank = bool(
                re.search(rf"(?:BLACKLIST|BL) 0?{rank}(?: |$)", key)
            ) or bool(re.search(rf"BL0?{rank}(?![0-9])", compact))
            has_name = bool(rival) and rival.upper() in key
            if not (has_rank or has_name):
                continue
            if "DEFEATED" in key or "DEFEAT" in key or "BEAT " in key:
                strong.append((location_id, str(name)))
            elif "BLACKLIST" in key and (
                "WIN" in key or "VICTORY" in key or "COMPLETE" in key
            ):
                fallback.append((location_id, str(name)))

        rows = strong or fallback
        if not rows:
            return 0, ""
        rows.sort(key=lambda item: item[0])
        return rows[0]

    def resolve_event_mapping(
        self,
        event_id: str,
        rival_rank: int = 0,
        activity: str = "",
        track_name: str = "",
        blacklist_rank: int = 0,
        race_kind: str = "",
        rival_stage: int = 0,
        rival_stages: int = 0,
        native_index: int = 0,
        native_count: int = 0,
    ) -> tuple[Optional[EventMapping], str]:
        event_id = event_id.strip()
        activity = activity.strip().casefold()

        def key(text):
            words = re.findall(
                r"[a-z0-9]+", str(text).casefold().replace("highway", "hwy")
            )
            return "".join(word for word in words if word != "and")

        def parts(row):
            marker = (
                " - Rival Race - "
                if row.mapping_source == "rival_race"
                else " - Race - "
            )
            suffix = row.location_name.partition(marker)[2]
            category, _, track = suffix.partition(" - ")
            return key(category), key(track)

        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", event_id)
        if match and int(match[1]) == 16:
            return None, "prologue_event"
        if race_kind in ("career", "rival") and 1 <= blacklist_rank <= 15:
            source = "career_race" if race_kind == "career" else "rival_race"
            pool = [
                row
                for row in self.event_map.values()
                if row.mapping_source == source
                and self._blacklist_rank_from_event(row.event_id) == blacklist_rank
            ]
            if race_kind == "career" and (native_index or native_count):
                rows = sorted(pool, key=lambda row: row.location_id)
                if native_count != len(rows) or not 1 <= native_index <= native_count:
                    return None, "native_career_roster_mismatch"
                return rows[native_index - 1], "native_career_roster"
            if race_kind == "rival" and rival_stage:
                rows = sorted(pool, key=lambda row: row.location_id)
                if (
                    rival_rank != blacklist_rank
                    or rival_stages != len(rows)
                    or not 1 <= rival_stage <= len(rows)
                ):
                    return None, "invalid_native_rival_stage"
                return rows[rival_stage - 1], "native_rival_stage"
            candidates = [
                row for row in pool if not activity or parts(row)[0] == key(activity)
            ]
            if track_name:
                named = [row for row in candidates if parts(row)[1] == key(track_name)]
                if len(named) == 1:
                    return named[0], "native_track_identity"
                if named:
                    return None, "ambiguous_native_track"
                return None, "native_track_not_in_slot"
            if len(candidates) == 1:
                return candidates[0], "unique_native_type"
            return None, "native_track_required"
        mapping = self.event_map.get(event_id)
        if mapping is not None:
            if not activity or parts(mapping)[0] == key(activity):
                return mapping, "exact"
            return None, "event_activity_mismatch"
        if event_id.lower().endswith(".r"):
            if not 1 <= rival_rank <= 15:
                return None, "rival_context_required"
            rows = self.rival_mappings_by_rank.get(rival_rank, [])
            return (
                (rows[-1], "rival_runtime_final")
                if rows
                else (None, "unmapped_rival_final")
            )
        if not match:
            return None, "invalid_event_id"
        rank, race_type, variant = map(int, match.groups())
        if not 1 <= rank <= 15:
            return None, "invalid_rank"

        category = {
            1: "Circuit",
            2: "Sprint",
            3: "Lap Knockout",
            4: "Tollbooth",
            5: "Speedtrap",
            7: "Drag",
        }.get(race_type, "")
        if not category or (activity and key(activity) != key(category)):
            return None, "event_activity_mismatch"
        source = "rival_race" if rival_rank else "career_race"
        pool = [
            row
            for row in self.event_map.values()
            if row.mapping_source == source
            and self._blacklist_rank_from_event(row.event_id) == rank
            and parts(row)[0] == key(category)
        ]
        if len(pool) == 1 and (not rival_rank or rival_rank == rank):
            return pool[0], "unique_event_type"
        return None, "unmapped_event"

    async def _send_blacklist_defeated_check(self, rank: int, event_id: str) -> None:
        if rank not in existing_blacklist_ranks(self.slot_data):
            return

        await self.send_blacklist_unlocked_check(rank)
        self.defeated_blacklist_ranks.add(rank)
        self._save_state()
        location_id, location_name = self._find_blacklist_defeated_location(rank)
        if not location_id:
            logger.warning(
                "Blacklist #%d was defeated after %s, but this seed exposes no matching Defeated location.",
                rank,
                event_id,
            )
            await self.broadcast(
                {
                    "type": "blacklist_defeat_ack",
                    "blacklist_rank": rank,
                    "event_id": event_id,
                    "location_sent": False,
                    "reason": "defeat_location_not_in_seed",
                }
            )
            await self.sync_blacklist_goal()
            return

        sent, reason = await self.send_location_check(
            location_id,
            source=f"Blacklist #{rank} defeated / runtime finale {event_id} / {location_name}",
        )
        logger.info(
            "BLACKLIST DEFEATED CHECK: rank #%d location=%d name=%s sent=%s reason=%s",
            rank,
            location_id,
            location_name,
            sent,
            reason,
        )
        await self.broadcast(
            {
                "type": "blacklist_defeat_ack",
                "blacklist_rank": rank,
                "event_id": event_id,
                "location_id": location_id,
                "location_name": location_name,
                "location_sent": sent,
                "reason": reason,
            }
        )
        await self.sync_blacklist_goal()

    def _verified_defeated_ranks(self) -> set[int]:
        proven = set()
        for rank, proof in getattr(self, "blacklist_defeat_proofs", {}).items():
            if (
                proof.get("version") == 3
                and proof.get("session") == self.session_key
                and proof.get("source") == "native_rival_scores"
                and 1 <= rank <= 15
            ):
                proven.add(rank)
                continue
            if (
                proof.get("version") == 2
                and proof.get("session") == self.session_key
                and proof.get("source")
                in ("native_career_progress", "native_career_complete")
                and 1 <= rank <= 15
                and not free_order_blacklist(self.slot_data)
            ):
                proven.add(rank)
                continue
            rows = self.rival_mappings_by_rank.get(rank, [])
            if (
                rows
                and proof.get("version") == 1
                and proof.get("rival_rank") == rank
                and proof.get("event_id") == rows[-1].event_id
            ):
                proven.add(rank)
        for rank in range(1, 16):
            location, _ = self._find_blacklist_defeated_location(rank)
            if location and location in self.checked_locations:
                proven.add(rank)
        return proven & existing_blacklist_ranks(self.slot_data)

    async def recover_native_progress(self, next_rank, defeated_mask=None):
        if (
            not 0 <= next_rank <= 15
            or not self.session_key
            or not self._session_state_loaded
        ):
            return False
        if free_order_blacklist(self.slot_data):
            if (
                type(defeated_mask) is not int
                or defeated_mask < 0
                or defeated_mask & ~0xFFFE
            ):
                await self.sync_blacklist_goal()
                return False
            ranks = {rank for rank in range(1, 16) if defeated_mask & (1 << rank)}
            version, source = 3, "native_rival_scores"
        else:
            ranks = set(range(next_rank + 1, 16))
            version, source = 2, (
                "native_career_complete" if next_rank == 0 else "native_career_progress"
            )
        ranks &= existing_blacklist_ranks(self.slot_data)
        proofs = self.__dict__.setdefault("blacklist_defeat_proofs", {})
        previous_proofs = dict(proofs)
        previous_defeated = set(self.defeated_blacklist_ranks)
        for rank in ranks:
            proofs[rank] = {
                "version": version,
                "session": self.session_key,
                "source": source,
            }
            self.defeated_blacklist_ranks.add(rank)
        if not self._save_state():
            self.blacklist_defeat_proofs = previous_proofs
            self.defeated_blacklist_ranks = previous_defeated
            self._native_progress_key = None
            return False
        for rank in sorted(ranks):
            await self.send_blacklist_unlocked_check(rank)
            location, _ = self._find_blacklist_defeated_location(rank)
            if location:
                await self.send_location_check(
                    location, source=f"Native Career progress past Blacklist #{rank}"
                )
        await self.sync_blacklist_goal()

        return True

    async def send_blacklist_unlocked_check(self, rank):
        if self.slot_data.get(
            "randomize_blacklist_unlocks", False
        ) and not self.has_blacklist_unlock(rank):
            return False
        if not 1 <= rank <= 15:
            return False
        location = 2600000 + (16 - rank) * 10 + 1
        if location not in self.server_locations:
            return False
        await self.send_location_check(
            location, source=f"Blacklist #{rank} challenge unlocked"
        )
        return (
            location in self.checked_locations
            or location in self.queued_location_checks
            or location in self.pending_checks
        )

    def _reward_check_status(self, location_id: int, rank: int) -> str:
        if location_id in getattr(self, "won_race_locations", set()):
            return "won"

        return "checked"

    async def refresh_reward_statuses(self) -> None:
        for location_id, entry in list(getattr(self, "reward_catalog", {}).items()):
            checked = location_id in self.checked_locations
            status = self._reward_check_status(
                location_id, _safe_int(entry.get("blacklist_rank", 0))
            )
            if entry.get("checked") != checked or entry.get("check_status") != status:
                entry["checked"], entry["check_status"] = checked, status
                await self.broadcast({"type": "reward_slot", **entry})

    async def sync_blacklist_goal(self) -> None:
        async with self._goal_sync_lock:
            now = asyncio.get_running_loop().time()
            retries = self.__dict__.setdefault("_check_retry_at", {})
            for location in list(self.pending_checks):
                if now >= retries.setdefault(location, now + 10.0):
                    self.pending_checks.discard(location)

            for rank in range(1, 16):
                location_id, _ = self._find_blacklist_defeated_location(rank)
                if location_id and location_id in self.checked_locations:
                    self.defeated_blacklist_ranks.add(rank)
            self._save_state()

            verified = self._verified_defeated_ranks()
            settings = goal_settings(self.slot_data)
            escaped = settings["goal"] == "final_escape" and final_escape_verified(
                getattr(self, "final_escape_proof", {}),
                self.session_key,
                self.slot_data,
            )
            complete = goal_completed(settings, verified, escaped)
            progress = goal_progress(settings, verified, escaped)
            needed = goal_required(settings)
            for rank in verified:
                await self.send_blacklist_unlocked_check(rank)
            signature = (progress, needed, complete)
            if signature != self._goal_progress_announced:
                self._goal_progress_announced = signature
                await self.broadcast(
                    {
                        "type": "goal_progress",
                        "defeated": len(verified),
                        "required": needed,
                        "progress": progress,
                        "description": goal_description(settings),
                        "complete": complete,
                    }
                )
            if not complete or not self.ap_connected() or not self.server_locations:
                return
            self.finished_game = True
            if not self._goal_announced or now >= getattr(
                self, "_goal_status_retry_at", 0
            ):
                announce = not self._goal_announced
                try:
                    await self.send_msgs(
                        [{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]
                    )
                except Exception as exc:
                    logger.warning("Goal status will retry on reconnect: %s", exc)
                    return
                self._goal_announced = True
                self._goal_status_retry_at = now + 30.0
                if announce:
                    await self.broadcast(
                        {
                            "type": "goal_complete",
                            "goal": self.slot_data.get("goal", "defeat_all_blacklist"),
                            "message": goal_description(settings) + " completed.",
                        }
                    )
                    logger.info(
                        "GOAL: %s; progress %d/%d. Release and collect follow the room settings.",
                        goal_description(settings),
                        progress,
                        needed,
                    )

    async def check_race_result(
        self,
        event_id: str,
        ranking: int,
        won: bool,
        rival_rank: int = 0,
        activity: str = "",
        track_name: str = "",
        blacklist_rank: int = 0,
        race_kind: str = "",
        rival_stage: int = 0,
        rival_stages: int = 0,
        native_index: int = 0,
        native_count: int = 0,
    ) -> None:
        mapping, resolution = self.resolve_event_mapping(
            event_id,
            rival_rank,
            activity,
            track_name,
            blacklist_rank,
            race_kind,
            rival_stage,
            rival_stages,
            native_index,
            native_count,
        )
        if not won or ranking != 1:
            await self.broadcast(
                {
                    "type": "race_result_ack",
                    "event_id": event_id,
                    "ranking": ranking,
                    "won": False,
                    "location_sent": False,
                    "reason": "not_won",
                }
            )
            return

        if mapping is None:
            logger.warning(
                "Won event %s but it did not resolve to an AP race (%s).",
                event_id,
                resolution,
            )
            await self.broadcast(
                {
                    "type": "race_result_ack",
                    "event_id": event_id,
                    "ranking": ranking,
                    "won": True,
                    "location_sent": False,
                    "reason": resolution,
                }
            )
            return

        if resolution in ("rank_index_fallback", "rival_runtime_final"):
            logger.info(
                "Career EventID %s matched %s by %s.",
                event_id,
                mapping.event_id,
                resolution,
            )

        event_rank = self._blacklist_rank_from_event(mapping.event_id)
        if mapping.mapping_source == "career_race" and not self.has_event_permit(
            event_rank
        ):
            await self.broadcast(
                {
                    "type": "race_result_ack",
                    "event_id": event_id,
                    "won": True,
                    "location_sent": False,
                    "reason": "event_permit_required",
                }
            )
            return
        if mapping.mapping_source == "rival_race" and rival_rank != event_rank:
            logger.warning(
                "Refusing rival result without matching native challenge context: event=%s rival_rank=%s",
                event_id,
                rival_rank,
            )
            await self.broadcast(
                {
                    "type": "race_result_ack",
                    "event_id": event_id,
                    "won": True,
                    "location_sent": False,
                    "reason": "rival_context_required",
                }
            )
            return

        if (
            mapping.mapping_source == "rival_race"
            and self.slot_data.get("randomize_blacklist_unlocks", False)
            and not self.has_blacklist_unlock(event_rank)
        ):
            await self.broadcast(
                {
                    "type": "race_result_ack",
                    "event_id": event_id,
                    "won": True,
                    "location_sent": False,
                    "reason": "blacklist_unlock_required",
                }
            )
            return
        self.__dict__.setdefault("won_race_locations", set()).add(mapping.location_id)
        self._save_state()
        sent, reason = await self.send_location_check(
            mapping.location_id,
            source=f"race {event_id} ({resolution}) / {mapping.location_name}",
        )
        await self.broadcast(
            {
                "type": "race_result_ack",
                "event_id": event_id,
                "ranking": ranking,
                "won": True,
                "location_id": mapping.location_id,
                "location_name": mapping.location_name,
                "location_sent": sent,
                "reason": reason,
            }
        )

        rank = self._blacklist_rank_from_event(mapping.event_id)
        rivals = self.rival_mappings_by_rank.get(rank, [])
        canonical_final = (
            mapping.mapping_source == "rival_race" and rivals and mapping == rivals[-1]
        )
        if resolution == "rival_runtime_final" or canonical_final:
            rank = (
                rival_rank
                if resolution == "rival_runtime_final"
                else self._blacklist_rank_from_event(mapping.event_id)
            )
            if rank is not None:
                self.__dict__.setdefault("blacklist_defeat_proofs", {})[rank] = {
                    "version": 1,
                    "event_id": mapping.event_id,
                    "rival_rank": rival_rank,
                }
                await self._send_blacklist_defeated_check(rank, event_id)

    async def purchase_shop_location(
        self,
        location_id: int,
        request_id: int = 0,
        expected_price: int = -1,
        expected_car: str = "",
    ) -> None:
        key = (location_id, request_id)
        if request_id > 0 and key in self.shop_purchase_results:
            await self.broadcast(self.shop_purchase_results[key])
            return
        if not self.ap_connected():

            result = {
                "type": "shop_purchase_ack",
                "location_id": location_id,
                "request_id": request_id,
                "accepted": False,
                "reason": "shop_requires_ap_connection",
            }
            self.shop_purchase_results[key] = result
            await self.broadcast(result)
            return
        meta = self.shop_locations.get(location_id)
        entry = self.shop_catalog.get(location_id)

        if meta is None:
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "accepted": False,
                    "reason": "not_shop_location",
                    "request_id": request_id,
                }
            )
            return

        if entry is None:
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "accepted": False,
                    "reason": "not_scouted_yet",
                    "request_id": request_id,
                }
            )
            return

        catalog_price = _safe_int(entry.get("price", 0))
        catalog_car = str(meta.car or "")
        if expected_price >= 0 and catalog_price != expected_price:
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "accepted": False,
                    "reason": "price_mismatch",
                    "request_id": request_id,
                    "price": catalog_price,
                }
            )
            return
        if (
            expected_car
            and catalog_car
            and _car_compare_key(expected_car) != _car_compare_key(catalog_car)
        ):
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "accepted": False,
                    "reason": "car_mismatch",
                    "request_id": request_id,
                }
            )
            return

        sent, reason = await self.send_location_check(
            location_id,
            source=f"shop purchase / {meta.location_name}",
            durable=False,
        )
        result = {
            "type": "shop_purchase_ack",
            "location_id": location_id,
            "accepted": sent,
            "reason": reason,
            "item_id": entry.get("item_id", 0),
            "item_name": entry.get("item_name", "Unknown item"),
            "recipient_player": entry.get("recipient_player", 0),
            "recipient_name": entry.get("recipient_name", "Unknown"),
            "recipient_game": entry.get("recipient_game", "Unknown"),
            "price": entry.get("price", 0),
            "request_id": request_id,
        }
        self.shop_purchase_results[key] = result
        await self.broadcast(result)

    async def resolve_shop_purchase(self, location_id: int, request_id: int) -> None:
        key = (location_id, request_id)
        result = self.shop_purchase_results.get(key)
        if result is not None:
            await self.broadcast(result)
            return

        if (
            location_id in self.checked_locations
            or location_id in self.pending_checks
            or location_id in self.queued_location_checks
        ):
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "request_id": request_id,
                    "accepted": True,
                    "reason": "reconciled_location_check",
                }
            )
        elif self.ap_connected():
            await self.broadcast(
                {
                    "type": "shop_purchase_ack",
                    "location_id": location_id,
                    "request_id": request_id,
                    "accepted": False,
                    "reason": "purchase_not_received",
                }
            )

    def on_package(self, cmd: str, args: dict):
        if self.session_rejected and cmd != "Connected":
            return
        if cmd == "Connected":
            self._ap_authenticated = False

            self._hint_confirmed = set()
            self._hint_pending = set()
            self._hint_retry_at = {}
            self.slot_data = args.get("slot_data", {}) or {}
            self.pending_checks.clear()
            logger.info("Connected to Archipelago as slot %s.", self.slot_name)
            started = getattr(self, "_connection_attempt_started", 0.0)
            if started:
                logger.info(
                    "AP PERF AUTHENTICATED: elapsed_ms=%d",
                    int((asyncio.get_running_loop().time() - started) * 1000),
                )
            logger.info("Slot data: %s", self.slot_data)

            try:
                self.configure_isolated_ap_session()
            except (RuntimeError, ValueError, OSError) as exc:
                self.session_rejected = True

                async def reject_session(message=str(exc)):
                    await self.connection_notice("error", message)
                    await self.disconnect()

                asyncio.create_task(reject_session())
                return

            self.reconcile_location_checks()
            self._ap_authenticated = True
            asyncio.create_task(self.subscribe_shared_hints())
            asyncio.create_task(self.configure_deathlink())
            asyncio.create_task(self.broadcast({"type": "request_milestone_journal"}))
            asyncio.create_task(self.broadcast({"type": "request_game_journal"}))

            asyncio.create_task(self.replay_seed_config())

            logger.info(
                "LIVE CHECK MODE: Career race checks=ON, "
                "pursuit milestone checks=%s, Photo Ticket checks=%s.",
                "ON" if self.enable_milestone_checks else "OFF",
                (
                    "PROBE ONLY"
                    if not self.enable_photo_ticket_checks
                    else "ON (saved camera completions)"
                ),
            )

            logger.info(
                "Archipelago item placement is seed-randomized. "
                "Successful checks will now return the randomized item "
                "assigned to that AP location."
            )

            if not self.in_game_connect:
                asyncio.create_task(self.ensure_game_launched())
            asyncio.create_task(self.refresh_setup_state())

            asyncio.create_task(
                self.broadcast(
                    {
                        "type": "ap_status",
                        "connected": True,
                        "slot": self.slot_name,
                        "location_count": len(self.missing_locations)
                        + len(self.checked_locations),
                        "checked_count": len(self.checked_locations),
                        "queued_checks": len(
                            self.queued_location_checks | self.pending_checks
                        ),
                    }
                )
            )
            asyncio.create_task(self.scout_shop_locations())
            asyncio.create_task(self.replay_shop_catalog())
            asyncio.create_task(self.flush_seen_hints())
            asyncio.create_task(self.flush_queued_location_checks())
            asyncio.create_task(self.sync_blacklist_goal())

        elif cmd == "ConnectionRefused":
            self._ap_authenticated = False
            asyncio.create_task(
                self.connection_notice(
                    "error", "Connection refused: " + ", ".join(args.get("errors", []))
                )
            )
        elif cmd == "LocationInfo":
            locations = args.get("locations", []) or []
            asyncio.create_task(self.process_location_info(locations))

        elif cmd == "ReceivedItems":
            start_index = _safe_int(args.get("index", 0))
            items = args.get("items", []) or []

            for offset, item in enumerate(items):
                index = start_index + offset
                already_delivered = index in self.delivered_received_indices

                item_id = _safe_int(getattr(item, "item", 0))
                source_player = _safe_int(getattr(item, "player", 0))
                source_location = _safe_int(getattr(item, "location", 0))
                item_name = self._resolve_item_name(item_id, self.game)
                source_name = self._player_name(source_player)
                item_meta = self.item_manifest.get(item_id)

                payload: dict[str, Any] = {
                    "type": "received_item",
                    "index": index,
                    "item_id": item_id,
                    "item_name": item_name,
                    "source_player": source_player,
                    "source_name": source_name,
                    "source_location": source_location,
                    "item_type": item_meta.item_type if item_meta else "unknown",
                    "car": item_meta.car if item_meta else "",
                    "category": item_meta.category if item_meta else "",
                    "tier": item_meta.tier if item_meta else "",
                    "session_key": self.session_key,
                    "notify": not already_delivered,
                }
                payload = self.filter_received_payload(payload, not already_delivered)
                self.known_received[index] = payload

                asyncio.create_task(self.queue_received_sms(index, payload))
                if not already_delivered:
                    self.pending_received[index] = payload
                    logger.info(
                        "Received item index=%d: %s (id=%d) from %s at location %d",
                        index,
                        item_name,
                        item_id,
                        source_name,
                        source_location,
                    )
                asyncio.create_task(self.broadcast(payload))

            asyncio.create_task(self.replay_blacklist_unlock_checks())
            asyncio.create_task(self.replay_seed_config())
            asyncio.create_task(self.refresh_setup_state())

        elif cmd == "RoomUpdate":
            self.reconcile_location_checks()
            asyncio.create_task(self.sync_blacklist_goal())
            for location_id, entry in self.shop_catalog.items():
                entry["checked"] = location_id in self.checked_locations
            for location_id, entry in self.reward_catalog.items():
                checked = location_id in self.checked_locations
                status = self._reward_check_status(
                    location_id, _safe_int(entry.get("blacklist_rank", 0))
                )
                if (
                    entry.get("checked") != checked
                    or entry.get("check_status") != status
                ):
                    entry["checked"] = checked
                    entry["check_status"] = status
                    asyncio.create_task(
                        self.broadcast({"type": "reward_slot", **entry})
                    )

            asyncio.create_task(
                self.broadcast(
                    {
                        "type": "ap_status",
                        "connected": self.ap_connected(),
                        "slot": self.slot_name,
                        "checked_count": len(self.checked_locations),
                        "queued_checks": len(
                            self.queued_location_checks | self.pending_checks
                        ),
                    }
                )
            )


async def handle_game_connection(
    ctx: NFSMWContext,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername")
    logger.info("NFSMW ASI connected from %s.", peer)
    try:
        raw_hello = await asyncio.wait_for(reader.readline(), timeout=5.0)
        hello = json.loads(raw_hello.decode("utf-8"))
        pid = _safe_int(hello.get("process_id", 0))
        owned_setup, bound_game = game_binding(
            hello, ctx.setup_token, ctx.session_key, ctx.setup_game_process is not None
        )
    except (ValueError, UnicodeError, asyncio.TimeoutError):
        writer.write(
            (
                json.dumps(
                    {
                        "type": "connection_status",
                        "phase": "error",
                        "message": "Launch using the updated AP client for an isolated save.",
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        writer.close()
        return
    ctx.game_writers.add(writer)
    ready_pid = (
        bound_game
        and not owned_setup
        and pid > 0
        and hello.get("build") in {NATIVE_BUILD, CLIENT_BUILD}
    )
    if ready_pid:
        ctx.game_ready_pids.add(pid)
        if (
            getattr(ctx, "desktop_mode", False)
            and os.name == "nt"
            and getattr(ctx, "desktop_game_process", None) is None
        ):
            try:
                from NFSMW_Desktop import AttachedGame

                ctx.desktop_game_process = AttachedGame(pid)
            except OSError:
                logger.warning(
                    "Could not attach the game lifetime monitor; the client will retry."
                )
    elif bound_game and not owned_setup and pid > 0:
        await ctx.connection_notice(
            "error",
            f"Native ASI build {hello.get('build', 'unknown')} is unsupported. This EXE client uses native ASI {NATIVE_BUILD}. Install that ASI before starting the game.",
        )
        logger.error(
            "Native ASI build mismatch: game=%s client=%s PID=%d",
            hello.get("build"),
            CLIENT_BUILD,
            pid,
        )
    if owned_setup:
        ctx.setup_native_pids.add(pid)
    if ctx.setup_game_process is not None:
        await ctx.broadcast(ctx.connection_message)
    elif ctx.ap_connected():
        await ctx.connection_notice(
            "connected", "Connected to Archipelago as " + ctx.slot_name
        )
    else:
        await ctx.connection_notice(
            "connecting",
            "AP disconnected; earned milestones will sync after reconnecting.",
        )

    await ctx.broadcast(
        {
            "type": "bridge_status",
            "connected": True,
            "ap_connected": ctx.ap_connected(),
            "client_build": CLIENT_BUILD,
        }
    )

    if ctx.server is not None and not ctx.ap_connected():
        logger.warning(
            "Archipelago WebSocket is open, but slot authentication is NOT complete yet. "
            "Wait for 'Room Information' and 'Connected to Archipelago as slot %s' before racing. "
            "If those lines never appear, restart MultiServer.",
            ctx.slot_name,
        )

    await ctx.replay_seed_config()
    await ctx.replay_shop_catalog()
    await ctx.replay_received_inventory()
    await ctx.replay_sms()

    try:
        while not reader.at_eof():
            try:
                raw = await reader.readline()
            except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                logger.info("NFSMW ASI connection closed by Windows: %s", exc)
                break

            if not raw:
                break

            try:
                msg = json.loads(raw.decode("utf-8").strip())
                if not isinstance(msg, dict):
                    raise ValueError("Expected a bridge JSON object")
            except Exception:
                logger.warning("Invalid bridge JSON discarded.")
                continue

            msg_type = msg.get("type")

            _, bound_game = game_binding(
                hello,
                ctx.setup_token,
                ctx.session_key,
                ctx.setup_game_process is not None,
            )

            if msg_type == "connection_ui_ready":
                if owned_setup and _safe_int(msg.get("ui_protocol", 0)) == 2:
                    ctx.setup_ui_ready = True
                    logger.info(
                        "The in-game server/slot/seed form is drawn and accepting input."
                    )
            elif msg_type == "career_context":
                if bound_game:
                    old_rank = getattr(ctx, "current_blacklist_rank", None)
                    ctx.observe_career_context(msg)
                    if getattr(ctx, "current_blacklist_rank", None) != old_rank:
                        await ctx.refresh_reward_statuses()
                        asyncio.create_task(ctx.sync_blacklist_goal())
            elif msg_type == "connect_request":
                if not owned_setup:
                    await ctx.connection_notice(
                        "error", "Restart the client to change the connection."
                    )
                    continue

                await ctx.connect_from_game(msg)
            elif msg_type == "bootstrap_purchase":
                if not owned_setup:
                    continue
                await ctx.buy_first_car()
            elif msg_type == "hello":
                logger.info("Game client hello: %s", msg)
                await ctx.broadcast(
                    {
                        "type": "bridge_status",
                        "connected": True,
                        "ap_connected": ctx.ap_connected(),
                        "client_build": CLIENT_BUILD,
                    }
                )
                await ctx.replay_seed_config()
                await ctx.replay_shop_catalog()
                await ctx.replay_received_inventory()

            elif owned_setup:
                continue

            elif not bound_game:
                continue

            elif msg_type == "game_journal":
                await ctx.accept_game_journal(msg)

            elif msg_type == "event_selected":
                event_id = str(msg.get("event_id", ""))
                logger.info("Career menu selected Event ID: %s", event_id)
                append_discovery_row(event_id, "career_menu")
                mapping, resolution = ctx.resolve_event_mapping(event_id)
                if mapping is not None and mapping.mapping_source == "rival_race":
                    mapping = None
                    resolution = "native_challenge_context_required"

                if mapping is not None:
                    logger.info(
                        "Career EventID mapping: %s -> %d (%s), source=%s",
                        event_id,
                        mapping.location_id,
                        mapping.location_name,
                        f"{mapping.mapping_source}/{resolution}",
                    )

                await ctx.broadcast(
                    {
                        "type": "event_selected_ack",
                        "event_id": event_id,
                        "mapped": mapping is not None,
                        "location_id": mapping.location_id if mapping else 0,
                        "location_name": mapping.location_name if mapping else "",
                    }
                )

            elif msg_type == "race_result":
                event_id = str(msg.get("event_id", ""))
                ranking = _safe_int(msg.get("ranking", 0))
                won = _bool(msg.get("won", False))
                logger.info(
                    "Game race result: event=%s ranking=%d won=%s",
                    event_id,
                    ranking,
                    won,
                )
                append_discovery_row(event_id, "race_result", str(ranking), str(won))
                await ctx.check_race_result(
                    event_id,
                    ranking,
                    won,
                    _safe_int(msg.get("rival_rank", 0)),
                    activity=str(msg.get("activity", "")),
                    track_name=str(msg.get("track_name", "")),
                    blacklist_rank=_safe_int(msg.get("blacklist_rank", 0)),
                    race_kind=str(msg.get("race_kind", "")),
                    rival_stage=_safe_int(msg.get("rival_stage", 0)),
                    rival_stages=_safe_int(msg.get("rival_stages", 0)),
                    native_index=_safe_int(msg.get("native_index", 0)),
                    native_count=_safe_int(msg.get("native_count", 0)),
                )

            elif msg_type == "career_bus_health":
                logger.info(
                    "NFSMW career event bus health event: %s",
                    msg.get("event_name", ""),
                )

            elif msg_type == "career_event_probe":
                append_career_probe_row(msg)

                logger.info(
                    "Career event probe captured: %s hash=%s handle=%s",
                    msg.get("event_name", ""),
                    msg.get("event_hash", ""),
                    msg.get("event_handle", ""),
                )

                if msg.get("event_name") == "MNotifyMilestoneReached":
                    logger.info(
                        "Milestone progress observed; native completed objectives "
                        "are reconciled by their own Blacklist rank."
                    )

            elif msg_type == "deathlink_bust":
                await ctx.send_arrest_deathlink(msg)

            elif msg_type == "deathlink_start_request":
                await ctx.authorize_deathlink(msg)

            elif msg_type == "deathlink_applied":
                ctx.confirm_deathlink(msg)

            elif msg_type == "milestone_journal":
                await ctx.accept_milestone_journal(msg)

            elif msg_type == "milestone_progress_decoded":
                append_milestone_decoded_row(msg)
                append_milestone_metric_row(msg)

                logger.info(
                    "Decoded milestone metric: event=%s metric=%s "
                    "category=%s value=%s descriptor=%s",
                    msg.get("event_name", ""),
                    msg.get("metric_name", "") or "<unknown>",
                    msg.get("ap_category", "") or "<unmapped>",
                    msg.get("value_float", ""),
                    msg.get("descriptor", ""),
                )

                ctx.log_milestone_candidate(msg)

            elif msg_type == "milestone_metric_string":
                append_milestone_metric_string_row(msg)

                logger.info(
                    "Milestone metric string candidate: %s = %s",
                    msg.get("address", ""),
                    msg.get("text", ""),
                )

            elif msg_type == "shop_purchase":
                location_id = _safe_int(msg.get("location_id", 0))
                logger.info("Game requested AP shop purchase check: %d", location_id)
                request_id = _safe_int(msg.get("request_id", 0))
                expected_price = _safe_int(msg.get("expected_price", -1), -1)
                expected_car = str(msg.get("expected_car", "") or "")
                await ctx.purchase_shop_location(
                    location_id, request_id, expected_price, expected_car
                )

            elif msg_type == "shop_purchase_status":
                await ctx.resolve_shop_purchase(
                    _safe_int(msg.get("location_id", 0)),
                    _safe_int(msg.get("request_id", 0)),
                )

            elif msg_type == "sms_notification_ack":
                ctx.acknowledge_sms(msg)
            elif msg_type == "received_item_ack":
                if ctx.acknowledge_received_item(msg):
                    logger.info(
                        "Game confirmed delivery of received item index %s.",
                        msg.get("index"),
                    )

            elif msg_type == "request_shop_catalog":
                await ctx.replay_shop_catalog()

            else:
                logger.info("Game bridge message: %s", msg)

    finally:
        ctx.game_writers.discard(writer)
        if ready_pid:
            ctx.game_ready_pids.discard(pid)
        try:
            writer.close()
        except Exception:
            pass
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug("Ignoring bridge shutdown exception: %r", exc)
        process = getattr(ctx, "game_process", None)
        code = process.poll() if process is not None else None
        if code is None:
            logger.info("NFSMW ASI disconnected. The game may still be running.")
        elif code:
            logger.error(
                "speed.exe exited with code %s (0x%08X). Check NFSMWArchipelago-crash.log in the game folder.",
                code,
                code & 0xFFFFFFFF,
            )
        else:
            logger.info("NFSMW ASI disconnected. The game exited normally.")


NFSMW_BRIDGE_HOST = "127.0.0.1"
NFSMW_BRIDGE_PORT = 38283


def launcher_connection_target(value: str) -> tuple[str, Optional[str], Optional[str]]:
    from urllib.parse import urlsplit, urlunsplit, unquote

    value = value.strip().replace("archipelago://", "ws://", 1)
    if value.isdigit():
        return normalize_server_address(value), None, None
    parsed = urlsplit(value if "://" in value else "ws://" + value)
    name = unquote(parsed.username) if parsed.username is not None else None
    password = unquote(parsed.password) if parsed.password is not None else None
    host = parsed.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    authority = host + (":" + str(parsed.port) if parsed.port is not None else "")
    address = urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, ""))
    return normalize_server_address(address), name, password


def normalize_server_address(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return value

    if value.isdigit():
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError(f"Invalid server port: {value}")
        return f"localhost:{port}"

    from urllib.parse import urlsplit

    value = value.replace("archipelago://", "ws://", 1)
    if value.startswith("http://"):
        value = "ws://" + value[7:]
    elif value.startswith("https://"):
        value = "wss://" + value[8:]
    parsed = urlsplit(value if "://" in value else "ws://" + value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Server port must be between 1 and 65535.") from exc
    if (
        parsed.scheme not in ("ws", "wss")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Use a host:port or ws/wss server link. Enter the password separately."
        )
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Server port must be between 1 and 65535.")
    return value


def load_config(path: Path):

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(path, encoding="utf-8")

    server = cfg.get(
        "Archipelago",
        "Server",
        fallback="",
    )
    slot = cfg.get(
        "Archipelago",
        "Slot",
        fallback="",
    )
    password = (
        cfg.get(
            "Archipelago",
            "Password",
            fallback="",
        )
        or None
    )

    host = NFSMW_BRIDGE_HOST
    port = NFSMW_BRIDGE_PORT

    auto_launch = cfg.getboolean(
        "Launcher",
        "AutoLaunch",
        fallback=True,
    )

    game_exe_text = os.path.expandvars(
        cfg.get(
            "Launcher",
            "GameExe",
            fallback=str(HERE / "speed.exe"),
        )
    )

    save_root_text = os.path.expandvars(
        cfg.get(
            "Launcher",
            "SaveRoot",
            fallback=(r"%USERPROFILE%\Documents\Archipelago\NFSMW"),
        )
    )

    from NFSMW_Wine import configuration_path

    game_exe_text = configuration_path(game_exe_text)
    save_root_text = configuration_path(save_root_text)

    enable_milestone_checks = cfg.getboolean(
        "Checks",
        "EnableMilestoneChecks",
        fallback=True,
    )

    enable_photo_ticket_checks = cfg.getboolean(
        "Checks",
        "EnablePhotoTrapChecks",
        fallback=True,
    )

    prompt_for_seed = False

    return (
        server,
        slot,
        password,
        host,
        port,
        auto_launch,
        Path(game_exe_text),
        Path(save_root_text),
        enable_milestone_checks,
        enable_photo_ticket_checks,
        prompt_for_seed,
    )


async def main(args=None) -> None:
    config_path = HERE / "NFSMW_AP_Client.ini"
    (
        server,
        slot,
        password,
        bridge_host,
        bridge_port,
        auto_launch,
        game_exe,
        save_root,
        enable_milestone_checks,
        enable_photo_ticket_checks,
        prompt_for_seed,
    ) = load_config(config_path)

    expected_seed_name = ""

    ctx = NFSMWContext(
        None,
        None,
        "",
        auto_launch_game=auto_launch,
        game_exe=game_exe,
        save_base_root=save_root,
        enable_milestone_checks=enable_milestone_checks,
        enable_photo_ticket_checks=enable_photo_ticket_checks,
        expected_seed_name=expected_seed_name,
    )

    ctx.desktop_mode = bool(getattr(args, "desktop", False))
    ctx.desktop_game_process = None
    if ctx.desktop_mode:
        args.desktop_session.attach(ctx)

    ctx.ap_launcher_ui = bool(getattr(args, "ap_text_window", False)) and not (
        getattr(args, "connection_screen_only", False) or getattr(args, "nogui", False)
    )
    if ctx.ap_launcher_ui:
        ctx.username = getattr(args, "name", None)
        ctx.password = getattr(args, "password", None)

    bridge_server = await asyncio.start_server(
        lambda r, w: handle_game_connection(ctx, r, w),
        bridge_host,
        bridge_port,
    )

    logger.info("Local NFSMW bridge listening on %s:%d.", bridge_host, bridge_port)
    watchdog = None
    screen_task = None
    game_exit_task = None
    try:
        if ctx.desktop_mode:
            from NFSMW_Desktop import watch_game_exit

            game_exit_task = asyncio.create_task(watch_game_exit(ctx))
        await ctx.launch_connection_screen()
        screen_task = asyncio.create_task(ctx.connection_screen.run())
        if ctx.ap_launcher_ui:
            ctx.run_gui()

            def gui_finished(task):
                if not task.cancelled() and task.exception():
                    logger.error("Archipelago client UI stopped: %s", task.exception())
                ctx.exit_event.set()

            ctx.ui_task.add_done_callback(gui_finished)
            logger.info(
                "Enter server, slot and password in the NFSMW connection screen. The AP client window shares this session for chat, hints and status."
            )
            if getattr(args, "connect", None):
                await ctx.connect(args.connect)
        else:
            logger.info(
                "Fullscreen NFSMW connection screen enabled. NFSMW starts after authentication."
            )
        watchdog = asyncio.create_task(ctx.setup_status_watchdog())
        async with bridge_server:
            await ctx.exit_event.wait()
    finally:
        if ctx.connection_screen is not None:
            ctx.connection_screen.close()
        if screen_task is not None:
            screen_task.cancel()
            await asyncio.gather(screen_task, return_exceptions=True)
        bridge_server.close()
        await bridge_server.wait_closed()
        if watchdog is not None:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
        if game_exit_task is not None:
            game_exit_task.cancel()
            await asyncio.gather(game_exit_task, return_exceptions=True)
        await ctx.shutdown()


def launch(*argv) -> None:
    from CommonClient import get_base_parser, handle_url_arg

    parser = get_base_parser(
        description="NFSMW Archipelago client with native game bridge, chat and hints"
    )
    parser.add_argument("--name", default=None, help="Archipelago slot name")
    parser.add_argument(
        "--ap-text-window",
        action="store_true",
        help="Also open the optional Archipelago graphical text window",
    )
    parser.add_argument(
        "--connection-screen-only",
        action="store_true",
        help="Open the NFSMW connection screen without the additional AP text window",
    )
    parser.add_argument(
        "url", nargs="?", help="archipelago:// connection link from the AP room"
    )
    args = handle_url_arg(parser.parse_args(argv), parser=parser)
    asyncio.run(main(args))


if __name__ == "__main__":
    try:
        launch(*sys.argv[1:])
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError) as exc:
        logger.error("NFSMW launch stopped: %s", exc)
        raise SystemExit(1) from None
