RIVAL_NAMES = {
    1: "Razor",
    2: "Bull",
    3: "Ronnie",
    4: "JV",
    5: "Webster",
    6: "Ming",
    7: "Kaze",
    8: "Jewels",
    9: "Earl",
    10: "Baron",
    11: "Big Lou",
    12: "Izzy",
    13: "Vic",
    14: "Taz",
    15: "Sonny",
}
FINAL_ESCAPE_EVENT = "1.8.1"
GOAL_TYPES = ("blacklist_count", "specific_blacklist", "final_escape")
GOAL_FIELDS = {
    "blacklist_count": ("goal_blacklist_count",),
    "specific_blacklist": ("goal_blacklist",),
    "final_escape": (),
}


def number(value, default=1):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if 1 <= value <= 15 else default


def goal_type(slot_data):
    mode = slot_data.get("goal")
    return mode if mode in GOAL_TYPES else "standard"


def free_order_blacklist(slot_data):
    return (
        bool(slot_data.get("randomize_blacklist_unlocks", False))
        or goal_type(slot_data) == "final_escape"
    )


def target_rank(slot_data):
    return number(slot_data.get("goal_blacklist", 1))


def goal_settings(slot_data):
    mode = goal_type(slot_data)
    settings = {"goal": slot_data.get("goal", "defeat_all_blacklist")}
    if mode == "blacklist_count":
        settings["goal_blacklist_count"] = number(slot_data.get("goal_blacklist_count", 15), 15)
    elif mode != "final_escape":
        settings["goal_blacklist"] = target_rank(slot_data)
    return settings


def career_goal_rank(slot_data):
    mode = goal_type(slot_data)
    if mode == "blacklist_count":
        return 16 - goal_required(slot_data)
    if mode == "final_escape":
        return 1
    return target_rank(slot_data)


def required_ranks(slot_data):
    mode = goal_type(slot_data)
    if mode == "specific_blacklist":
        return {target_rank(slot_data)}
    if mode in ("blacklist_count", "final_escape"):
        return set(range(1, 16))
    return set(range(target_rank(slot_data), 16))


def goal_required(slot_data):
    if goal_type(slot_data) == "final_escape":
        return 16
    if goal_type(slot_data) == "blacklist_count":
        return number(slot_data.get("goal_blacklist_count", 15), 15)
    return len(required_ranks(slot_data))


def goal_progress(slot_data, defeated, escaped=False):
    ranks = {rank for rank in defeated if type(rank) is int and 1 <= rank <= 15}
    mode = goal_type(slot_data)
    if mode == "final_escape":
        return len(ranks) + int(bool(escaped) and required_ranks(slot_data).issubset(ranks))
    if mode == "blacklist_count":
        return min(len(ranks), goal_required(slot_data))
    return len(required_ranks(slot_data) & ranks)


def goal_completed(slot_data, defeated, escaped=False):
    return goal_progress(slot_data, defeated, escaped) >= goal_required(slot_data)


def goal_description(slot_data):
    mode = goal_type(slot_data)
    if mode == "blacklist_count":
        count = goal_required(slot_data)
        return f"Defeat {count} distinct Blacklist " + ("racer" if count == 1 else "racers")
    if mode == "specific_blacklist":
        rank = target_rank(slot_data)
        return f"Defeat Blacklist #{rank}: {RIVAL_NAMES[rank]}"
    if mode == "final_escape":
        return "Defeat all 15 Blacklist rivals in any order, then escape the final chase"
    return f"Defeat the Blacklist through #{target_rank(slot_data)}"


def final_escape_verified(proof, session):
    return bool(
        session
        and isinstance(proof, dict)
        and proof.get("version") == 2
        and proof.get("session") == session
        and proof.get("source") == "native_final_escape"
        and proof.get("epic_pursuit") is True
        and proof.get("evaded") is True
        and proof.get("event_id") == FINAL_ESCAPE_EVENT
        and proof.get("defeated_blacklist_mask") == 0xFFFE
    )
