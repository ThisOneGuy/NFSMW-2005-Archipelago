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
        "true: give the included Blacklist rivals different randomized cars and appearances. "
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
        "- multiplied: multiply bounty earned during pursuits and from milestone and speedtrap rewards by bounty_multiplier. "
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
        "Multiply bounty earned during pursuits, including milestone and speedtrap rewards. This does not change the bounty target "
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
            raise ValueError(
                "Bounty multiplier must be a number from 0.01 to 100."
            ) from None
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


class ShopCarCount(Range):
    display_name = "Cars with Shop Checks"
    range_start = 0
    range_end = 32
    default = 32
    __doc__ = (
        "Choose how many of the 32 customizable cars have randomized shop locations. "
        "0 means no shop checks; 8 means eight cars; 32 means all cars. "
        "The cars are chosen once for each seed. Your free first car is included when the count is above zero. "
        "The same selection is used for performance and visual shops, according to the options below. "
        "Other cars keep normal shops, with all standard parts unlocked at normal prices. "
        "This does not remove cars or dealership checks. "
        "It has no effect when both shuffle_performance_parts and visual_store_checks are false."
    )


class ShufflePerformanceParts(Toggle):
    display_name = "Randomize Performance Parts"
    __doc__ = (
        "true: add performance upgrade unlocks and performance shop checks for the cars selected by shop_car_count. "
        "Each car's shop checks require that car. "
        "false: unlock all normal performance upgrades from the start, at their usual prices, with no Archipelago item requirements or shop checks. "
        "Visual shops are controlled separately by visual_store_checks."
    )


class VisualStoreChecks(Toggle):
    display_name = "Randomize Visual Shops"
    __doc__ = (
        "true: add body and visual shop checks for the cars selected by shop_car_count, including body kits, "
        "spoilers, rims, paint, vinyls and window tint. Each check requires its matching car. "
        "false: unlock all normal body and visual parts from the start, at their usual prices, with no Archipelago item requirements or shop checks."
    )


class RevealEventRewards(Toggle):
    display_name = "Show Race and Milestone Rewards"
    __doc__ = (
        "true: show event rewards and allow Visual Client reveals for accessible locations. "
        "false: keep original event names and disable Visual Client reward reveals. "
        "Car shops require the matching car; events require an Event Permit; rival races also require their Rival Challenge Permit when shuffled. "
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
        "values or weights. Cars, upgrade unlocks and Rival Challenge Permits are not trap exclusions."
    )


class RandomizeBlacklistUnlocks(Toggle):
    display_name = "Randomize Blacklist Unlocks"
    __doc__ = (
        "true: each rival needs their Blacklist Rival Challenge Permit item before you can race them. "
        "You must also meet their normal race, milestone and bounty requirements. "
        "The rival selector opens from the start. Without Event Permits, the city and regular events also start open. "
        "With Event Permits, city areas and regular events follow those permits. "
        "Beating a rival leaves their unfinished races and milestones available. "
        "In multiplayer, your permits are placed in other players' worlds. "
        "false: use normal Career progression, unless the Final Escape goal is selected."
    )

    @classmethod
    def from_text(cls, text):
        if text.strip().lower() in ("multiworld", "other_players"):
            return cls(1)
        return super().from_text(text)


class BlacklistEventPermits(Choice):
    display_name = "Blacklist Event Permits"
    option_disabled = 0
    option_individual = 1
    option_progressive = 2
    default = 0
    __doc__ = (
        "Choose how normal races and milestones unlock. Sonny's (#15) events always start open. "
        "disabled: keep the usual event access for your other settings. "
        "individual: add a Blacklist #X Event Permit for each included rival except Sonny. "
        "Each opens that rival's normal races, pursuit milestones and speedtraps. "
        "progressive: add one Progressive Blacklist Event Permit per included rival except Sonny. "
        "The first opens #14, the second #13, continuing to the last included rival. "
        "With all 15 members included, either mode adds 14 items. "
        "The event selector opens from the start. Event permits open that rival's regular events and the city areas needed for them, "
        "but do not grant rival-fight access. "
        "Rival Challenge Permits and the normal challenge requirements remain separate."
        " In logic, events and rival fights require a car from the vanilla dealership tier "
        "available after beating the previous rival, or a later tier. Sonny accepts any car. "
        "This car rule does not prevent early attempts in the game."
    )


class BlacklistExistCount(Range):
    display_name = "Blacklist Members in This Seed"
    range_start = 1
    range_end = 15
    default = 15
    __doc__ = (
        "Choose how many Blacklist members exist in this seed, starting at Sonny (#15). "
        "15 includes everyone; 5 includes Sonny, Taz, Vic, Izzy and Big Lou (#15 through #11). "
        "Excluded members have no race, milestone, unlock or defeat checks, and no permit items. "
        "Event Permits shrink to match: one fewer permit than included members. "
        "This setting is separate from the goal's defeat count. When goal is blacklist_count, "
        "a larger goal_blacklist_count automatically raises this count to match. A specific-rival "
        "goal must target an included member. Final Escape requires every included "
        "member, then the final chase."
    )


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
        "final_escape: defeat every included rival in any order, then escape the final police chase. "
        "Final Escape opens the city and rival selector. Regular events open unless Event Permits are enabled. Normal rival requirements and "
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
        "With normal progression, you work up from Sonny; with randomized unlocks, any five included rivals count. "
        "If this value exceeds blacklist_exist_count, that count is automatically raised to match."
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
    shop_car_count: ShopCarCount
    bounty_mode: BountyMode
    bounty_multiplier: BountyMultiplier
    death_link: DeathLink
    trap_percentage: TrapPercentage
    shuffle_performance_parts: ShufflePerformanceParts
    visual_store_checks: VisualStoreChecks
    reveal_event_rewards: RevealEventRewards
    excluded_traps: ExcludedTraps
    randomize_blacklist_unlocks: RandomizeBlacklistUnlocks
    blacklist_exist_count: BlacklistExistCount
    blacklist_event_permits: BlacklistEventPermits
    goal: Goal
    goal_blacklist_count: GoalBlacklistCount
    goal_blacklist: GoalBlacklist
