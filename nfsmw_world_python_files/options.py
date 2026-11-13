from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from Options import (
    Choice,
    DefaultOnToggle,
    FreeText,
    PerGameCommonOptions,
    Range,
    Toggle,
    OptionSet,
)


class StartingCar(Choice):
    __doc__ = (
        "Choose the pool for your free dealership car: all customizable cars, or the "
        "original starter cars."
    )
    display_name = "Guaranteed Dealership Car"

    option_randomized = 0
    option_vanilla_starter_pool = 1
    default = 0

    @classmethod
    def from_text(cls, text: str):
        if text.lower() == "random":
            return cls(cls.option_randomized)
        return super().from_text(text)


class RandomizeBlacklistCars(DefaultOnToggle):
    __doc__ = "Randomize the vehicle driven by each of the 15 Blacklist racers."
    display_name = "Randomize Blacklist Cars"


class RandomizeOpponentCars(DefaultOnToggle):
    __doc__ = "Randomize normal opponent vehicles."
    display_name = "Randomize Opponent Cars"


class ShopPriceMultiplier(Range):
    __doc__ = (
        "Set prices for Archipelago shop checks as a percentage. 100 is the normal price scale."
    )
    display_name = "Shop Price Multiplier"
    range_start = 25
    range_end = 500
    default = 100


class IncomingItemPriceMultiplier(Range):
    __doc__ = (
        "Set purchase prices for received cars and parts as a percentage. 100 is normal; "
        "0 makes them free."
    )
    display_name = "Incoming Item Price Multiplier"
    range_start = 0
    range_end = 500
    default = 100


class BountyMode(Choice):
    __doc__ = (
        "Choose normal bounty earnings, multiplied earnings, or no bounty requirement. "
        "The multiplier changes earnings only. Race and milestone targets still apply in "
        "every mode."
    )
    display_name = "Bounty System"
    option_original = 0
    option_multiplied = 1
    option_removed = 2
    alias_no_bounty_requirement = 2
    default = 0


class BountyMultiplier(FreeText):
    __doc__ = (
        "Bounty earned in Multiplied mode is multiplied by this number. Use 0.01 to 100, "
        "with up to two decimal places. For example, 2 doubles earnings and 0.5 halves "
        "them. Rival requirements stay the same."
    )
    display_name = "Bounty Multiplier"
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


class DeathLink(DefaultOnToggle):
    __doc__ = "Getting busted sends a DeathLink. Receiving one starts a pursuit."
    display_name = "DeathLink"


class DeathLinkPenalty(Choice):
    __doc__ = (
        "Receiving a DeathLink starts a pursuit at your current Career heat cap. Older "
        "YAML option names are still accepted."
    )
    display_name = "DeathLink Penalty"

    option_money = 0
    option_impound = 1
    option_money_and_impound = 2
    option_pursuit = 3
    default = 3


class DeathLinkMoneyPenalty(Range):
    __doc__ = "Kept for older YAML files. DeathLink now starts a pursuit instead of deducting cash."
    display_name = "DeathLink Money Penalty"
    range_start = 0
    range_end = 1_000_000
    default = 10_000


class TrapPercentage(Range):
    __doc__ = (
        "Percentage of cash filler replaced with driving traps. Cars and parts are not "
        "replaced. Traps activate while driving and pause in menus."
    )
    display_name = "Trap Percentage"
    range_start = 0
    range_end = 100
    default = 20


class ShufflePerformanceParts(DefaultOnToggle):
    display_name = "Shuffle Performance Parts"
    __doc__ = (
        "Include performance upgrades in the item pool and performance shop checks. Turn "
        "off to buy upgrades without Archipelago unlocks."
    )


class VisualStoreChecks(DefaultOnToggle):
    display_name = "Visual Store Checks"
    __doc__ = (
        "Include visual shop purchases as checks: body kits, spoilers, rims, paint, "
        "vinyls and other cosmetic parts. Turn off to use normal visual customization."
    )


class RevealEventRewards(DefaultOnToggle):
    display_name = "Reveal Event Rewards"
    __doc__ = (
        "Show item rewards in race and milestone menus. Turn off to hide these rewards "
        "and their automatic hints. You can still request hints manually."
    )


class AutoHintOnPreview(DefaultOnToggle):
    display_name = "Automatic Hints When Viewing Items"
    __doc__ = (
        "Share a hint when you preview a car, part, visual item or event reward in game. "
        "Turn off to keep previews private. You can still request or reveal hints "
        "manually."
    )


class Traps(DefaultOnToggle):
    display_name = "Traps"
    __doc__ = (
        "Allow driving traps. Turn off to remove them from your item pool and ignore any "
        "traps received."
    )


class ExcludedTraps(OptionSet):
    display_name = "Excluded Traps"
    valid_keys = {"Turbo Trap", "Brake Trap", "Flash Bang Trap", "Truck Trap", "Speedbreaker Trap"}
    __doc__ = "Choose which traps to leave out. Selecting all five disables every trap."


class RandomizeBlacklistUnlocks(Toggle):
    display_name = "Randomized Blacklist Members"
    __doc__ = (
        "Make Blacklist unlocks randomized items. Each rival needs their unlock item and "
        "the usual race, milestone and bounty targets. Opens the full map and regular "
        "events, and lets you browse all 15 rivals. In multiplayer, unlocks are placed in "
        "other players' worlds. An unlock cannot be placed among its own rival's rewards."
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
        "Defeat a set number of Blacklist racers, beat one specific rival, or escape the "
        "final chase after Razor. Only the selected goal counts toward completion."
    )


class GoalBlacklistCount(Range):
    display_name = "Blacklist Racers to Defeat"
    range_start = 1
    range_end = 15
    default = 15
    __doc__ = (
        "Defeat this many different Blacklist racers. Rematches count once. With "
        "randomized unlocks, any rivals count. Used only for the Blacklist Count goal."
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
        "Choose the rival to defeat for the Specific Blacklist goal. With normal Career "
        "progression, you'll still need to work your way up to them."
    )


@dataclass
class NFSMWOptions(PerGameCommonOptions):
    starting_car: StartingCar
    randomize_blacklist_cars: RandomizeBlacklistCars
    randomize_opponent_cars: RandomizeOpponentCars
    shop_price_multiplier: ShopPriceMultiplier
    incoming_item_price_multiplier: IncomingItemPriceMultiplier
    bounty_mode: BountyMode
    bounty_multiplier: BountyMultiplier
    death_link: DeathLink
    death_link_penalty: DeathLinkPenalty
    death_link_money_penalty: DeathLinkMoneyPenalty
    trap_percentage: TrapPercentage
    shuffle_performance_parts: ShufflePerformanceParts
    visual_store_checks: VisualStoreChecks
    reveal_event_rewards: RevealEventRewards
    auto_hint_on_preview: AutoHintOnPreview
    traps: Traps
    excluded_traps: ExcludedTraps
    randomize_blacklist_unlocks: RandomizeBlacklistUnlocks
    goal: Goal
    goal_blacklist_count: GoalBlacklistCount
    goal_blacklist: GoalBlacklist
