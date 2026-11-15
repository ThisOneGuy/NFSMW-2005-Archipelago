from decimal import Decimal, InvalidOperation


def bounty_settings(slot_data):
    mode = slot_data.get("bounty_mode", "original")
    if isinstance(mode, int) and not isinstance(mode, bool):
        mode = {0: "original", 1: "multiplied", 2: "removed"}.get(mode, "original")
    mode = str(mode).strip().casefold().replace(" ", "_")
    if mode == "no_bounty_requirement":
        mode = "removed"
    if mode not in ("original", "multiplied", "removed"):
        raise ValueError("The server supplied an invalid bounty mode.")
    try:
        factor = Decimal(str(slot_data.get("bounty_multiplier", 1)))
    except (InvalidOperation, ValueError):
        raise ValueError("The server supplied an invalid bounty multiplier.") from None
    if (
        not factor.is_finite()
        or not Decimal("0.01") <= factor <= Decimal("100")
        or factor * 100 != (factor * 100).to_integral_value()
    ):
        raise ValueError(
            "The server bounty multiplier must be 0.01–100, with up to two decimal places."
        )
    return {
        "bounty_mode": mode,
        "bounty_multiplier_percent": int(factor * 100) if mode == "multiplied" else 100,
    }
