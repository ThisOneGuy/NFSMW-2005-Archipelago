import re

TRAPS = {
    1950001: "Turbo Trap",
    1950002: "Brake Trap",
    1950003: "Flash Bang Trap",
    1950004: "Truck Trap",
    1950005: "Speedbreaker Trap",
}
CASH = {1900001: 5000, 1900002: 10000, 1900003: 25000}


def trap_allowed(slot_data, item_id=None):
    try:
        schema = int(slot_data.get("schema_version", 0))
    except (TypeError, ValueError):
        return False
    if schema < 6 and not slot_data.get("traps", False):
        return False
    try:
        percentage = int(slot_data.get("trap_percentage", 0))
    except (TypeError, ValueError):
        return False
    try:
        allowed = set(TRAPS.values()).intersection(
            slot_data.get("enabled_traps", TRAPS.values())
        ) - set(slot_data.get("excluded_traps", ()))
    except TypeError:
        return False
    if not 0 < percentage <= 100:
        return False
    return bool(allowed) if item_id is None else TRAPS.get(item_id) in allowed


def cash_price(price, item_id=0, item_type="", item_name=""):
    amount = CASH.get(item_id, 0) if item_type == "cash" else 0
    match = re.fullmatch(r"\$([0-9,]+) Cash", item_name)
    if not amount and match:
        amount = int(match.group(1).replace(",", ""))
    return min(price, amount // 2) if amount > 0 else price
