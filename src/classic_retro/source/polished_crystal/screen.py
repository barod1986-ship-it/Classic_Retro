"""The room the short strings really have on the engine-patched screens.

The extractor gives a string the width of its English when nothing else is known
(``units.make_slot``: "the English fits"), and the research notes on the engine's
strings (``data/engine_strings.json``) hold widths as free text that
``extract.first_int`` reads only when it starts with a number. For many menu
items, labels, name fields and prefixes that default is far below what the
screen holds, and the engine patch widened several boxes for Arabic labels.

``ROOM`` gives those entries the room read from the engine-patched code: the
coordinates a string is placed at, its box or menu frame, what is drawn next
to it, the fixed byte copies it goes through (13-byte names, 10-byte
nicknames, 19-byte string buffers) and the pixel field of a variable-width
string. Each rule is keyed by entry id; ``apply`` writes it into the entry's
limits and the encoder's slots, so that the manifest, the checker and the
encoder agree. A rule may also narrow an entry whose English default was too
generous (a label a value is drawn over).

A rule is a mapping of:

- ``width``: cells, for every slot, or a list of cells per slot;
- ``pad``: pad the slot with spaces to this many cells (a separator the code
  relies on, as a space before a number appended after the string);
- ``lead``: ``""`` drops the English's leading spaces (a name the code now
  composes with a space of its own);
- ``bytes``: the bytes a line may take (a fixed copy; the terminator apart);
- ``cols``: the columns ``[[start, cells], ...]`` of a line drawn as columns;
- ``vwf_px``: the pixels of a variable-width-font field (checked by the
  encoder with the font's Arabic glyph widths);
- ``ph``: placeholder widths for this entry (a buffer whose content is known);
- ``note``: what a translator needs to know about the room.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PACK = "engine/items/pack:"
_BATTLE = "engine/battle/menu:"
_PC = "engine/pc/bills_pc_ui:BillsPC_MenuStrings"
_START = "engine/menus/start_menu:StartMenu."
_CONTINUE = "engine/menus/intro_menu:Continue_LoadMenuHeader."
_AREA = "engine/pokedex/area:Pokedex_AreaTypeLists"
_DECO = "data/decorations/names#"

_TIME_OF_DAY_NOTE = (
    "the time of day: '<h:mm> <this>' on the main menu (ends at x 15), alone on the "
    "Pokégear clock, '<this> <hour> <o'clock>' when the clock is set and '<this> "
    "<how it was caught>' on the summary; an adverb reads well in all of them"
)

ROOM: dict[str, Mapping[str, Any]] = {
    # --- battle menus (engine/battle/menu.asm, widened for Arabic) -----------------
    # 2D menu, text from box x + 2: main menu (4,12)-(19,17), spacing 6: columns at
    # x 6 (5 cells, the second column's cursor at 11) and 12 (7 cells, frame at 19).
    _BATTLE + "BattleMenuDataHeader.Strings[0]": {"width": 5},
    _BATTLE + "BattleMenuDataHeader.Strings[1]": {"width": 7},
    _BATTLE + "BattleMenuDataHeader.Strings[2]": {"width": 5},
    _BATTLE + "BattleMenuDataHeader.Strings[3]": {"width": 7},
    # Contest (2,12)-(19,17), spacing 8: columns at x 4 and 12, 7 cells each; the
    # Park Ball count is drawn at x 4 + 5, so the ball label keeps 5.
    _BATTLE + "ContestBattleMenuDataHeader.Strings[0]": {"width": 7},
    _BATTLE + "ContestBattleMenuDataHeader.Strings[1]": {"width": 7},
    _BATTLE + "ContestBattleMenuDataHeader.Strings[2]": {
        "width": 5,
        "note": "the ball count is drawn 5 cells right of the label's start",
    },
    _BATTLE + "ContestBattleMenuDataHeader.Strings[3]": {"width": 7},
    # Safari (4,12)-(19,17), spacing 8: columns at x 6 (7 cells) and 14 (5 cells);
    # the Safari Ball count is drawn at (11,14), 5 cells right of the label.
    _BATTLE + "SafariBattleMenuDataHeader.Strings[0]": {
        "width": 5,
        "note": "the ball count is drawn 5 cells right of the label's start",
    },
    _BATTLE + "SafariBattleMenuDataHeader.Strings[1]": {"width": 5},
    _BATTLE + "SafariBattleMenuDataHeader.Strings[2]": {"width": 7},
    _BATTLE + "SafariBattleMenuDataHeader.Strings[3]": {"width": 5},
    # --- start menu: (9,0)-(19,17), text from x 11 to 18 ---------------------------
    **{
        _START + name: {"width": 8}
        for name in (
            "PokedexString",
            "PartyString",
            "PackString",
            "SaveString",
            "OptionString",
            "ExitString",
            "PokegearString",
            "QuitString",
        )
    },
    # --- bag item submenus: (11,y)-(19,11), text from x 13 to 18 --------------------
    **{
        _PACK + label: {"width": 6}
        for label in (
            "MenuDataHeader_UseGiveToss.MenuData2[0]",
            "MenuDataHeader_UseGiveToss.MenuData2[1]",
            "MenuDataHeader_UseGiveToss.MenuData2[2]",
            "MenuDataHeader_UseGiveToss.MenuData2[3]",
            "MenuDataHeader_Use.MenuData2[0]",
            "MenuDataHeader_Use.MenuData2[1]",
            "MenuDataHeader_Quit.MenuData2",
            "MenuDataHeader_UseSel.MenuData2[0]",
            "MenuDataHeader_UseSel.MenuData2[1]",
            "MenuDataHeader_UseSel.MenuData2[2]",
            "MenuDataHeader_GiveToss.MenuData2[0]",
            "MenuDataHeader_GiveToss.MenuData2[1]",
            "MenuDataHeader_GiveToss.MenuData2[2]",
        )
    },
    # --- Bill's PC: one table for menus of three widths (text at box x + 2): the
    # storage menu (9,4) has 8 cells, the party and box menus (10,y) 7, the mail
    # and item menus (11,y) 6 (Cancel is in every menu).
    _PC + "[0]": {"width": 6},
    _PC + "[1]": {"width": 8},
    **{f"{_PC}[{index}]": {"width": 7} for index in range(2, 11)},
    **{f"{_PC}[{index}]": {"width": 6} for index in range(11, 16)},
    # --- Continue / save box (0,0)-(15,9): labels from x 1, values at x 13 (badges,
    # 2 digits), 12 (dex, 3 digits) and 9 (time, hhh:mm); one cell left blank.
    _CONTINUE + "MenuData2_Dex[1]": {"width": 11},
    _CONTINUE + "MenuData2_Dex[2]": {"width": 10},
    _CONTINUE + "MenuData2_Dex[3]": {"width": 7},
    _CONTINUE + "MenuData2_NoDex[1]": {"width": 11},
    _CONTINUE + "MenuData2_NoDex[3]": {"width": 7},
    # --- trainer card: the dex label at (2,10), the count at (15,10) -----------------
    "engine/menus/trainer_card:TrainerCard_Page1_PrintDexCaught_GameTime.Dex_PlayTime_BP[0]": {
        "width": 12
    },
    # --- Hyper Training menu: (0,4)-(19,11), spacing 8: columns at x 2 (7 cells)
    # and 10 (9 cells); items go left, right, left, ...
    **{
        f"engine/pokemon/move_mon:Special_HyperTrain.Strings[{index}]": {
            "width": 9 if index % 2 else 7
        }
        for index in range(6)
    },
    # --- stat words ------------------------------------------------------------------
    # StatStrings: copied as ITEM_NAME_LENGTH (13) bytes into wStringBuffer2 and
    # shown in item messages ("<stat> of <mon> rose"): 12 bytes and cells.
    **{
        f"data/battle/stat_strings:StatStrings.{stat}": {
            "width": 12,
            "bytes": 12,
            "note": "item messages put it after a noun (its value): a definite noun",
        }
        for stat in ("health", "attack", "defense", "speed", "sp_atk", "sp_def")
    },
    # StatNames: GetStatName copies a 19-byte buffer (wStringBuffer2, 12 cells in the
    # battle texts), which put it before the Pokémon (an idafa): a bare noun.
    **{
        f"data/battle/stat_names#{index}": {
            "width": 12,
            "note": "battle texts put it before the Pokémon's name: a bare noun",
        }
        for index in range(8)
    },
    # The level-up stat box: names from (7-n,5) one a row, values 9 cells right.
    "engine/pokemon/mon_stats:AllStatNames": {"width": 8},
    # --- nicknames of a new Egg: copied into a 10-cell nickname ---------------------
    "engine/pokemon/move_mon:String_Egg": {"width": 10, "bytes": 10},
    "engine/events/daycare:DayCare_GenerateEgg.String_EGG": {"width": 10, "bytes": 10},
    "engine/events/odd_egg:GiveSpecialEgg.EggName": {"width": 10, "bytes": 10},
    "engine/events/wonder_trade:DoWonderTrade.EggString": {"width": 10, "bytes": 10},
    # --- the default box name: "<this> <n>" in a 9-byte box name (8 cells) ----------
    "engine/pc/bills_pc:InitializeBoxes.Box": {
        "width": 5,
        "pad": 6,
        "bytes": 6,
        "note": "the box number (1-2 digits) is appended after it, a space between",
    },
    # --- TM/HM names: "<prefix> <nn>" (the engine adds the space) in item-name
    # slots of 12 cells.
    "engine/items/tmhm2:_GetTMHMName.TMText": {
        "width": 9,
        "note": "the engine appends a space and the two-digit number: '<this> 01'",
    },
    "engine/items/tmhm2:_GetTMHMName.HMText": {
        "width": 9,
        "note": "the engine appends a space and the two-digit number: '<this> 01'",
    },
    # --- the side whose Mist/Safeguard/Light Screen/Reflect ends: the whole subject
    # ("your Pokémon" / "the foe's Pokémon") copied into wStringBuffer1.
    "engine/battle/endturn:GetTurnAndPlacePrefix.Your": {
        "width": 13,
        "note": "the whole subject (your Pokémon), shown as {ram:wStringBuffer1} in the "
        "texts that tell a Mist, Safeguard, Light Screen or Reflect ended",
    },
    "engine/battle/endturn:GetTurnAndPlacePrefix.Foe": {
        "width": 13,
        "note": "the whole subject (the foe's Pokémon), shown as {ram:wStringBuffer1} in "
        "the texts that tell a Mist, Safeguard, Light Screen or Reflect ended",
    },
    **{
        f"data/text/battle:{label}": {"ph": {"{ram:wStringBuffer1}": 13}}
        for label in (
            "BattleText_MistFaded",
            "BattleText_SafeguardFaded",
            "BattleText_LightScreenFell",
            "BattleText_ReflectFaded",
        )
    },
    # --- the Pokédex area label: VWF, drawn right to left from pixel 53 -------------
    **{
        f"{_AREA}[{index}]": {
            "width": 11,
            "vwf_px": 53,
            "note": "proportional font: at most 53 pixels (most letters 5-7)",
        }
        for index in range(11)
    },
    # --- decorations: whole names and the parts GetDecoName composes as
    # "<noun> <modifier>" into wStringBuffer2, shown in 12-cell texts and menus.
    **{f"{_DECO}{index}": {"width": 12} for index in range(14)},
    **{
        f"{_DECO}{index}": {
            "width": 12,
            "lead": "",
            "note": "the noun; the engine adds a space and the modifier after it",
        }
        for index in range(14, 18)
    },
    _DECO + "18": {
        "width": 12,
        "lead": "",
        "pad": None,
        "note": "comes after the Pokémon's name (the engine adds the space): a big doll",
    },
    **{
        f"{_DECO}{index}": {"width": 12, "note": "comes after the noun bed (masculine)"}
        for index in range(19, 23)
    },
    **{
        f"{_DECO}{index}": {
            "width": 12,
            "note": "comes after the noun carpet (feminine)",
        }
        for index in range(23, 27)
    },
    # --- Exp. Candy jar: names at x 13 to 18, the count on the next row -------------
    **{
        f"engine/items/item_effects:CandyJar_MonSelected.CandyNames[{index}]": {
            "width": 6,
            "note": "the size of the Exp. Candy, alone on its row",
        }
        for index in range(5)
    },
    # --- Apricorn box: colours at x 7 (5 cells) and 13 (6 cells), counts below ------
    **{
        f"engine/items/item_effects:ApricornBox.Text[{index}]": {
            "width": 12,
            "cols": [[0, 5], [6, 6]],
        }
        for index in (0, 2, 4)
    },
    "engine/items/item_effects:ApricornBox.Text[6]": {"width": 5},
    # --- summary: the rental label fills the 12-cell window; the OT label of the
    # trade screen keeps 3 cells (the gender symbol is drawn at x 7).
    "engine/pokemon/summary/pink_page:SummaryScreen_PinkPage.Rental_OT[0]": {"width": 12},
    "engine/pokemon/summary/pink_page:SummaryScreen_PinkPage.Rental_OT[1]": {"width": 10},
    "engine/movie/trade_animation:TrademonStats_OTMonData": {"width": 3},
    # Met line: "<time of day> <this>[number]" composed into one string at (1,14),
    # 18 cells (time of day 5 + space + this + up to 3 digits printed right after it).
    "engine/pokemon/summary/orange_page:SummaryScreen_OrangePage.str_level": {
        "width": 8,
        "pad": 9,
        "note": "after the time of day; the level number follows it (a space is added)",
    },
    "engine/pokemon/summary/orange_page:SummaryScreen_OrangePage.str_hatched": {
        "width": 12,
        "note": "after the time of day",
    },
    "engine/pokemon/summary/orange_page:SummaryScreen_OrangePage.str_traded": {
        "width": 12,
        "note": "after the time of day",
    },
    # --- clock words: the time of day ends at x 15 after "hh:mm " on the main menu (9
    # cells), heads the summary's met line (5, see above) and shares row 9 of the
    # clock setting with the hour and o'clock ("<this> hh <o'clock>", x 1-18).
    **{
        f"engine/rtc/timeset:{label}": {"width": 5, "note": _TIME_OF_DAY_NOTE}
        for label in ("NITE_String", "MORN_String", "DAY_String", "EVE_String")
    },
    "engine/rtc/timeset:String_oclock": {
        "width": 9,
        "note": "'<time of day> <hour> <this>' from (1,9): read first, right of the hour",
    },
    **{
        f"engine/events/std_scripts:DayToTextScript.{day}Text": {"width": 8}
        for day in ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
    },
    # --- the diploma's body: flush right at x 17, inside the margins x 2-17 ---------
    "engine/events/diploma:PlaceDiplomaPage1OnScreen.DiplomaString": {"width": 16},
    # --- naming screen: End, Del and the page switch end at x 6, 12 and 18 ----------
    **{
        f"engine/menus/naming_screen:NamingScreen_DrawBorders.{label}": {"width": 5}
        for label in ("EndString", "DelString", "PageString")
    },
}


def apply(entry: dict[str, Any]) -> bool:
    """Give the entry the room its rule says; ``False`` when it has no rule."""
    rule = ROOM.get(entry["id"])
    if rule is None:
        return False
    limits = entry["limits"]
    slots = (entry.get("fmt") or {}).get("slots") or []
    if "width" in rule:
        widths = rule["width"]
        if entry["kind"] == "box" or not slots:
            limits["width"] = widths if isinstance(widths, int) else max(widths)
        else:
            per_slot = [widths] * len(slots) if isinstance(widths, int) else list(widths)
            if len(per_slot) != len(slots):
                raise ValueError(f"{entry['id']}: {len(per_slot)} widths for {len(slots)} lines")
            for slot, width in zip(slots, per_slot, strict=True):
                slot["width"] = width
            limits["width"] = max(per_slot)
            if len(set(per_slot)) > 1:
                limits["line_widths"] = per_slot
            else:
                limits.pop("line_widths", None)
    for slot in slots:
        if "lead" in rule:
            slot["ctl_before"] = rule["lead"]
        if "pad" in rule:
            if rule["pad"] is None:
                slot.pop("pad", None)
            else:
                slot["pad"] = rule["pad"]
        if "bytes" in rule:
            slot["bytes"] = rule["bytes"]
        if "cols" in rule:
            slot["cols"] = rule["cols"]
    if "pad" in rule:
        if any(slot.get("pad") is not None for slot in slots):
            limits["pad"] = True
        else:
            limits.pop("pad", None)
    if "cols" in rule:
        limits["cols"] = rule["cols"]
    if "vwf_px" in rule:
        limits["vwf_px"] = rule["vwf_px"]
    if "ph" in rule:
        limits["ph"] = {**limits.get("ph", {}), **rule["ph"]}
    if "note" in rule:
        note = limits.get("note")
        limits["note"] = f"{note} {rule['note']}" if note else rule["note"]
    return True
