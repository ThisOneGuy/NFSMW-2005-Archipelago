from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from Options import (
    Choice,
    FreeText,
    PerGameCommonOptions,
    Range,
    Toggle,
    OptionSet,
)

from .items import TRAP_ITEMS


class StartingCar(Choice):
    __doc__ = (
        "Choose the pool for the free car at the first dealership. "
        "randomized: pick from all supported customizable cars. "
        "vanilla_starter_pool: pick a Punto, Cobalt SS, IS 300 or Golf GTI. "
        "You still choose and buy the free car in the dealership; it is not added to your garage automatically."
    )
    display_name = "Free Dealership Car"

    option_randomized = 0
    option_vanilla_starter_pool = 1
    default = 0

    @classmethod
    def from_text(cls, text: str):
        if text.lower() == "random":
            return cls(cls.option_randomized)
        return super().from_text(text)


class RandomizeBlacklistCars(Toggle):
    __doc__ = (
        "true: give the 15 Blacklist rivals different randomized cars and appearances. "
        "false: keep their original cars and appearances. "
        "This changes their vehicles, not the items needed to unlock their challenges."
    )
    display_name = "Randomize Blacklist Cars"


class RandomizeOpponentCars(Toggle):
    __doc__ = (
        "true: randomize the cars used by normal race opponents. "
        "false: use the game's normal opponent cars. "
        "Blacklist rivals have their own car-randomization setting."
    )
    display_name = "Randomize Opponent Cars"


class ShopPriceMultiplier(Range):
    __doc__ = (
        "Scale the cash price of purchases that send Archipelago items. "
        "100 means normal prices, 50 means half price and 200 means double price. "
        "Allowed values: 25 to 500. The guaranteed first car stays free."
    )
    display_name = "AP Shop Prices (%)"
    range_start = 25
    range_end = 500
    default = 100


class BountyMode(Choice):
    __doc__ = (
        "Choose how bounty works.\n\n"
        "- original: normal earnings and normal rival bounty targets. Ignores bounty_multiplier.\n"
        "- multiplied: multiply the bounty you earn during pursuits by bounty_multiplier. "
        "Rival bounty targets stay unchanged.\n"
        "- removed: remove the bounty target for rival challenges. "
        "Earnings stay normal and bounty_multiplier is ignored.\n\n"
        "Race wins and milestone requirements still apply in every mode. "
        "For double bounty earnings, use bounty_mode: multiplied and bounty_multiplier: 2."
    )
    display_name = "Bounty System"
    option_original = 0
    option_multiplied = 1
    option_removed = 2
    alias_no_bounty_requirement = 2
    default = 0


class BountyMultiplier(FreeText):
    __doc__ = (
        "Multiply bounty you earn during pursuits. This does not change the bounty target "
        "needed to challenge a Blacklist rival. Only bounty_mode: multiplied uses this value.\n\n"
        "1 = normal earnings; 2 = double; 0.5 = half. With 2, a 1,000-bounty award becomes "
        "2,000, while a 20,000-bounty rival target remains 20,000. "
        "Use a number from 0.01 to 100, with up to two decimal places.\n\n"
        "Example YAML for double earnings::\n\n"
        "  bounty_mode: multiplied\n"
        '  bounty_multiplier: "2"\n\n'
        "The original and removed modes ignore this multiplier. Changing it will not affect "
        "a seed that was already generated."
    )
    display_name = "Bounty Earnings Multiplier"
    default = "1"

    def __init__(self, value):
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("Bounty multiplier must be a number from 0.01 to 100.") from None
        if not amount.is_finite() or not Decimal("0.01") <= amount <= Decimal("100"):
            raise ValueError("Bounty multiplier must be a number from 0.01 to 100.")
        if amount * 100 != (amount * 100).to_integral_value():
            raise ValueError("Bounty multiplier supports up to two decimal places.")
        super().__init__(format(amount.normalize(), "f"))


class DeathLink(Toggle):
    __doc__ = (
        "true: getting busted sends a DeathLink to the other players using it. "
        "Receiving a DeathLink starts a police pursuit at your current Career heat cap. "
        "false: do not send or receive DeathLinks."
    )
    display_name = "DeathLink"


class TrapPercentage(Range):
    __doc__ = (
        "Choose how much cash filler is replaced with traps. "
        "20 means 20% of those filler items become traps; car and upgrade items are kept. "
        "Allowed values: 0 to 100. At 0, no traps are placed and received traps have no effect. "
        "Trap effects run while driving, not in menus."
    )
    display_name = "Trap Item Percentage"
    range_start = 0
    range_end = 100
    default = 0


class ShufflePerformanceParts(Toggle):
    display_name = "Randomize Performance Parts"
    __doc__ = (
        "true: add performance upgrade unlocks to the item pool and make performance shop purchases into checks. "
        "Each car's shop checks require that car. "
        "false: use normal upgrades, prices and Career unlocks, with no Archipelago item requirements. "
        "Visual shops are controlled separately by visual_store_checks."
    )


class VisualStoreChecks(Toggle):
    display_name = "Randomize Visual Shops"
    __doc__ = (
        "true: turn body and visual shop purchases into Archipelago checks, including body kits, "
        "spoilers, rims, paint, vinyls and window tint. Each check requires its matching car. "
        "false: use normal customization prices and Career unlocks, with no Archipelago checks in those shops."
    )


class RevealEventRewards(Toggle):
    display_name = "Show Race and Milestone Rewards"
    __doc__ = (
        "true: show the Archipelago reward in race and milestone menus. "
        "false: keep the game's original race and milestone names without reward or scouting text. "
        "The races and milestones still count as checks. "
        "Viewing a reward does not share a hint; hints must be requested or revealed manually."
    )


class ExcludedTraps(OptionSet):
    display_name = "Trap Types to Exclude"
    valid_keys = set(TRAP_ITEMS)
    __doc__ = (
        "Choose which trap items to leave out. Used when trap_percentage is greater than 0. "
        "[] means exclude nothing. Listed traps are not placed and do nothing if received.\n\n"
        "Available item names (use the exact spelling):\n\n"
        "- Turbo Trap: briefly forces forward acceleration.\n"
        "- Brake Trap: applies the brakes for three seconds.\n"
        "- Flash Bang Trap: briefly covers the screen with a white flash.\n"
        "- Truck Trap: spawns a truck to hit your car.\n"
        "- Speedbreaker Trap: empties the Speedbreaker meter.\n\n"
        "Example YAML to exclude two trap items::\n\n"
        "  excluded_traps:\n"
        '    - "Flash Bang Trap"\n'
        '    - "Truck Trap"\n\n'
        "Excluding all five disables every trap. This list takes item names, not true/false "
        "values or weights. Cars, upgrade unlocks and Challenge Permits are not trap exclusions."
    )


class RandomizeBlacklistUnlocks(Toggle):
    display_name = "Randomize Blacklist Unlocks"
    __doc__ = (
        "true: each rival needs their Blacklist Challenge Permit item before you can race them. "
        "You must also meet their normal race, milestone and bounty requirements. "
        "The city and regular events open from the start, and the rival selector lets you choose any rival. "
        "Beating a rival leaves their unfinished races and milestones available. "
        "In multiplayer, your permits are placed in other players' worlds. "
        "false: use normal Career progression, unless the Final Escape goal is selected."
    )

    @classmethod
    def from_text(cls, text):
        if text.strip().lower() in ("multiworld", "other_players"):
            return cls(1)
        return super().from_text(text)


class Goal(Choice):
    display_name = "Goal"
    option_blacklist_count = 0
    option_specific_blacklist = 1
    option_final_escape = 2
    default = 0
    __doc__ = (
        "Choose what finishes your Archipelago game. "
        "blacklist_count: defeat the number set by goal_blacklist_count. "
        "specific_blacklist: defeat the rival named by goal_blacklist. "
        "final_escape: defeat all 15 rivals in any order, then escape the final police chase. "
        "Final Escape opens the city, regular events and rival selector. Normal rival requirements and "
        "any randomized permit items still apply. Only the settings for the selected goal are used."
    )


class GoalBlacklistCount(Range):
    display_name = "Blacklist Rivals to Defeat"
    range_start = 1
    range_end = 15
    default = 15
    __doc__ = (
        "Used only when goal is blacklist_count. Enter a number from 1 to 15. "
        "For example, 5 finishes after five different rival wins. Rematches do not add to the count. "
        "With normal progression, you work up from Sonny; with randomized unlocks, any five rivals count."
    )


class GoalBlacklist(Choice):
    display_name = "Target Blacklist Rival"
    option_razor = 1
    option_bull = 2
    option_ronnie = 3
    option_jv = 4
    option_webster = 5
    option_ming = 6
    option_kaze = 7
    option_jewels = 8
    option_earl = 9
    option_baron = 10
    option_big_lou = 11
    option_izzy = 12
    option_vic = 13
    option_taz = 14
    option_sonny = 15
    alias_all_blacklist = 1
    default = 1
    __doc__ = (
        "Used only when goal is specific_blacklist. For example, goal_blacklist: baron finishes after beating Baron (#10). "
        "With normal progression, you still need to work up to your target. "
        "Allowed names: sonny, taz, vic, izzy, big_lou, baron, earl, jewels, kaze, ming, webster, jv, ronnie, bull, razor."
    )


@dataclass
class NFSMWOptions(PerGameCommonOptions):
    starting_car: StartingCar
    randomize_blacklist_cars: RandomizeBlacklistCars
    randomize_opponent_cars: RandomizeOpponentCars
    shop_price_multiplier: ShopPriceMultiplier
    bounty_mode: BountyMode
    bounty_multiplier: BountyMultiplier
    death_link: DeathLink
    trap_percentage: TrapPercentage
    shuffle_performance_parts: ShufflePerformanceParts
    visual_store_checks: VisualStoreChecks
    reveal_event_rewards: RevealEventRewards
    excluded_traps: ExcludedTraps
    randomize_blacklist_unlocks: RandomizeBlacklistUnlocks
    goal: Goal
    goal_blacklist_count: GoalBlacklistCount
    goal_blacklist: GoalBlacklist
