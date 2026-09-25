"""Arabic translation of the *Mega Man Battle Network* (USA) opening.

A new game starts on Lan's first morning, which runs from two scenes and the
house between them (script archives of the Silenthal/bn1 disassembly):

- ``story_00``: MegaMan wakes Lan up from his PET, reads him the net news and
  a mail from his father (``Scene_Story_00``, 9 sections);
- Lan's room and the living room: picking up the PET and MegaMan's good
  morning, Mom and breakfast, and what Lan reads when he checks the room's
  things on that morning (the maps' dialogue archives), and MegaMan's advice
  on the L Button in both rooms (their commentary archives);
- ``story_01``: in front of the house Mayl is waiting, and the three walk to
  school while she tells them about the oven accidents (13 sections, then two
  empty ones the scene never runs).

Both scenes are translated whole; of the room archives, every section that can
run on that morning. Their other sections (later days) are copied unchanged.
For each translated section the original is pinned by its archive, its index,
the SHA-256 of its script (up to and including its ending command) and its
command skeleton (commands in order; line ends and item names excluded), so
the translation can be checked without the ROM and the ROM build can refuse a
different script.

The Arabic lives in ``classic_retro/translations/mmbn.json``: logical
Unicode Arabic in the engine's notation
(``engines.mmbn``). They keep every command of the original, in order: ``<``
and ``>`` move the speaker's mouth, ``\\p`` waits for a key, ``{cls N}`` clears
the box, ``{d N}``/``{fd N}`` wait inside the text, and the ``{raw ...}``
commands set flags, give items or animate Lan. Line ends (``\\n``) may move.
Item names, printed from the game's tables in English (``{key 0}`` is the
PET), are written as text; Latin words (PET, WWW, MegaMan.EXE, Recov10 A, the
buttons) keep the game's own glyphs.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.mmbn import Piece, notation_skeleton, parse_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class MmbnScriptArchive:
    """A script archive, the pointers to it and its number of sections."""

    key: str
    address: int
    references: tuple[int, ...]
    sections: int


@dataclass(frozen=True, slots=True)
class MmbnArabicSection:
    key: str
    archive: str
    index: int
    speaker: str
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


ARCHIVES = (
    # Scene_Story_00_LanWakesUp reads its archive through the literal at 0x08082AB0.
    MmbnScriptArchive("story_00", 0x0872954C, (0x08082AB0,), 9),
    # DialogueData_Offline: ACDC area, Lan's room and the living room.
    MmbnScriptArchive("lan_room", 0x086F2DD4, (0x08014DB4,), 235),
    MmbnScriptArchive("living_room", 0x086F1DC4, (0x08014DB0,), 235),
    # CommentaryData_Offline: what MegaMan says when the player presses L.
    MmbnScriptArchive("lan_room_talk", 0x086B42FC, (0x08015010,), 230),
    MmbnScriptArchive("living_room_talk", 0x086B2F9C, (0x0801500C,), 230),
    # Scene_Story_01 (the walk to school) reads its archive through 0x08082DCC.
    MmbnScriptArchive("story_01", 0x08729828, (0x08082DCC,), 15),
)

# key: (archive, section, speaker, SHA-256 of the original script, its commands)
# fmt: off
_SOURCES: dict[str, tuple[str, int, str, str, str]] = {
    "wake-up.0": ("story_00", 0, "megaman", "041cb51f661f13144c9deb3240227b715726f7bcac63157a9cd62e7cc8c3f81c", "{dialog_up}<>\\p{cls 5}{jump 1}"),
    "wake-up.1": ("story_00", 1, "lan", "ba5693df1aa82e192e135d2102cc65702f0555f67dddf5f169ad9ae1702698b8", "{pic 0 0}{dialog_up}{a 0}{d 30}{d 30}{d 30}{a 0}\\p{cls 5}{jump 2}"),
    "wake-up.2": ("story_00", 2, "megaman", "7124d877709f362030ac23669dd90ad0559d0585bd241a2d7134a6eaf064735e", "{hidepic}{dialog_up}<>\\p{cls 5}{jump 3}"),
    "wake-up.3": ("story_00", 3, "lan", "aadb61c1d3c59dbcb6171836b264bafcd2e1d0c50deefe7822eb8469de45b86d", "{pic 0 0}{dialog_up}{a 0}{d 30}{d 30}{d 30}{a 0}\\p{cls 5}{jump 4}"),
    "wake-up.4": ("story_00", 4, "megaman", "ab455442e31bfc2fa08fe7498a48e156ddcb49337e85b1de40cb6f50dd4ac6c7", "{hidepic}{dialog_up}<>\\p{cls 0}<>\\p{cls 5}{jump 5}"),
    "wake-up.5": ("story_00", 5, "lan", "a6d09ac6afbf41540982b4cc78f9501ce42778111ce3ddb196799d00144a465a", "{pic 0 0}{dialog_up}<>\\p{cls 5}{jump 6}"),
    "wake-up.6": ("story_00", 6, "megaman", "2b9ccca2bc6616f9b8015e058dbcbc98a640066e23f2688e326ecc4071c2dacb", "{hidepic}{dialog_up}<>\\p{cls 0}<>\\p{cls 0}<>\\p{cls 0}<>\\p{end 5}"),
    "wake-up.7": ("story_00", 7, "lan", "a6b93f3c99d84e98a67731e25d6e05779cd5c1531eef8f3fde6c7efeec3ce78d", "{pic 0 0}{dialog_up}<>{d 30}<>\\p{cls 5}{jump 8}"),
    "wake-up.8": ("story_00", 8, "megaman", "6d0c3ee102d178836f52ae449a2d0db33409538cb92f9ee9719358da5b9570d6", "{hidepic}{dialog_up}<>\\p{end 5}"),
    "lan-room.00": ("lan_room", 0x00, "narration", "fa28f3b443df702412ba298fa4176f0b3fc64091fc7dbaf39c680d31b81a9b8d", "{dialog_up}{raw F3 00 80 02}{raw F3 04 10 04}{raw FA 00}{raw FA 04 1E}{raw F7 00 00 01 FF FF FF}{raw FA 0C}{raw FA 04 04}{raw FA 08}\\p{cls 0}\\p{cls 0}{raw FA 00}{raw FA 04 1E}{raw FC 00 85 00}{raw FA 0C}{raw FA 04 04}{raw FA 08}\\p{cls 0}{dialog_down}{hidepic}{jump 2}"),
    "lan-room.01": ("lan_room", 0x01, "narration", "5af28948c2361851c8aca5632a05b80437cc495508c9850c3f202759fd70af4d", "{dialog_up}\\p{end 5}"),
    "lan-room.02": ("lan_room", 0x02, "megaman", "f1f5d1f17b15c41e6c6ddfebf74d0c35c3c7767f0d2d886be3adb3a0ccc52355", "{pic 34 0}{dialog_up}<>\\p{cls 0}{jump 3}"),
    "lan-room.03": ("lan_room", 0x03, "lan", "59e1d2a6befdbe3ca9697cce2c657e28b246fad5b4f07cacbe57be6406e64d49", "{pic 0 0}{dialog_up}<>\\p{cls 0}{jump 4}"),
    "lan-room.04": ("lan_room", 0x04, "megaman", "96be035d29a7897a44bbbb5fe0bd50ccf45e1434afa3b529be1ea418399f0667", "{pic 34 0}{dialog_up}<>\\p{cls 0}<>\\p{end 0}"),
    "lan-room.07": ("lan_room", 0x07, "megaman", "fc8434ed279225df540d8981d1e82e5e31c948d6d7a281f9b1e665efbe5aefb7", "{pic 34 0}{dialog_up}<>\\p{end 5}"),
    "lan-room.08": ("lan_room", 0x08, "megaman", "c1227998a075bd42611da8c3f449e4e12acc391142dda432fc43d0d3317a7dcf", "{pic 34 0}{dialog_up}{raw F3 08 00 00}{raw F3 08 01 00}<>\\p{end 5}"),
    "lan-room.0C": ("lan_room", 0x0C, "megaman", "70e739042d9a8de2f6a9e426b44c2a72e9ce4a7706026b56926ba54e6258343d", "{pic 34 0}{dialog_up}<>\\p{end 5}"),
    "lan-room.DC": ("lan_room", 0xDC, "narration", "96d3ca5809990d26edb545d215c09ffbffe0924a238c7d6d8f262da3d7b7ec8f", "{raw F4 00 81 02 DD FF}{dialog_up}\\p{end 5}"),
    "lan-room.DE": ("lan_room", 0xDE, "narration", "b3a7646e764b7dcb05b79dffdabbae6445ee23325e2820eca8a7aff615345433", "{dialog_up}\\p{cls 0}\\p{end 5}"),
    "lan-room.DF": ("lan_room", 0xDF, "narration", "5ec0b858b68a4ea325e32d08fbf42727e8bb560d2e3a3a2eab7277d1e16cdc40", "{raw F4 00 80 02 E0 FF}{dialog_up}\\p{end 5}"),
    "lan-room.E0": ("lan_room", 0xE0, "narration", "abffe834314c43357ba9fbe4c3a77ec68781ed3fc5b32e77ebae870d883a7682", "{dialog_up}\\p{end 5}"),
    "lan-room.E1": ("lan_room", 0xE1, "narration", "731bb9e16ea49b496f6c8a99ee62a0e9b84af5a8528fd988003b82474da5328a", "{dialog_up}\\p{end 5}"),
    "lan-room-talk.01": ("lan_room_talk", 0x01, "megaman", "a9b36ac391dcfaee33bd67cc178af8853b1859a1df6fc8d1f8dc020cbd7bd8c6", "{pic 34 0}{dialog_up}<>\\p{end 5}"),
    "living-room.00": ("living_room", 0x00, "mom", "7d55c4bb80d90990875897c0a2570d4f4218e2698d088709370d0ed2d26911a7", "{raw F4 00 96 00 04 FF}{raw F3 00 96 00}{pic 12 0}{dialog_up}<>\\p{cls 5}{jump 2}"),
    "living-room.01": ("living_room", 0x01, "narration", "2e5af92fa6ccce264e725aa2c14470cf26c919834cc2298c03e06a773f87dd54", "{dialog_up}{d 30}{d 30}\\p{cls 0}\\p{cls 0}{raw F3 00 86 02}{raw FA 00}{raw FA 04 1E}{raw F7 10 43 00 01 FF FF FF}{raw FA 0C}{raw FA 08}\\p{end 5}"),
    "living-room.02": ("living_room", 0x02, "lan", "acd38f47360d14b07554fe708902a4d2cf2d84e63538ce4eddd73fffaf5d0a2c", "{pic 0 0}{dialog_up}<>\\p{cls 5}{jump 3}"),
    "living-room.03": ("living_room", 0x03, "mom", "f2dd1ddf808bdc4168dde02be37b3d75c2535418080b02e7fd0e7820ad7b95fa", "{pic 12 0}{dialog_up}<>\\p{end 5}"),
    "living-room.04": ("living_room", 0x04, "mom", "a72430eec49cd967bb7e0b52377badf29201b17c2f3ce4eae9f16fa279fdd4a3", "{pic 12 0}{dialog_up}<>\\p{end 5}"),
    "living-room.DC": ("living_room", 0xDC, "narration", "388571e2222307522dd4146c64d21136273199879a954ad30f4edea9579974a6", "{dialog_up}\\p{end 5}"),
    "living-room.DD": ("living_room", 0xDD, "narration", "ab8d6c61f8b0da682a00d29bd83c2608433a6e26deca00a21c71ea942f74c263", "{raw F4 04 04 04 E7 FF}{raw F4 04 03 05 E6 FF}{raw F4 04 23 27 E5 FF}{dialog_up}\\p{end 5}"),
    "living-room.DE": ("living_room", 0xDE, "narration", "dd4c16c84c0c8d4ece71fd9f3d4a22ad4a8f4c8b5986afeb7303748cecbd3e48", "{raw F4 04 04 04 E7 FF}{raw F4 04 03 05 E6 FF}{dialog_up}\\p{end 5}"),
    "living-room.DF": ("living_room", 0xDF, "narration", "7cfd40417a4817eb16806233b1fe1d3a2897f484b93adb81277728a18a770ba4", "{raw F4 04 04 04 E7 FF}{raw F4 04 03 05 E6 FF}{raw F4 04 06 5F E0 FF}{dialog_up}\\p{end 5}"),
    "living-room.E1": ("living_room", 0xE1, "narration", "d7dd297874d4fd4f012d9e633a249444eaf656b1189e5f418e8baacb32b6d4dc", "{dialog_up}\\p{end 5}"),
    "living-room.E2": ("living_room", 0xE2, "narration", "484f4f41e35e2e401b35fa62ad982e5590c09d230480fbec1a70e81b02067299", "{dialog_up}\\p{end 5}"),
    "living-room.E3": ("living_room", 0xE3, "narration", "4a8a450c324aa6bad211724135a7294e024c1c44fdd0c3cafd02cbd1e1d6586d", "{dialog_up}\\p{end 5}"),
    "living-room.E4": ("living_room", 0xE4, "narration", "477de94d11318c571c2b9eb5c605f5469bcec741389563fe1161f3460272b6df", "{dialog_up}\\p{end 5}"),
    "living-room-talk.01": ("living_room_talk", 0x01, "megaman", "ce8ad43331500360b1d01fc6002b34b762c65ee2ad26f35603a4c0a03bfced49", "{pic 34 0}{dialog_up}<>\\p{end 5}"),
    "to-school.0": ("story_01", 0, "mayl", "821ab91ecaa459d2b0a9ed1c43e615dfec463ed00617b7eb1b418abce07144f0", "{pic 8 0}{dialog_up}<>\\p{cls 5}{jump 1}"),
    "to-school.1": ("story_01", 1, "megaman", "e2b54156811659edc7d383a83178962850d47e9a46234f335340cef7c7ddd8e2", "{pic 34 0}{dialog_up}<>{d 30}<>\\p{cls 5}{jump 2}"),
    "to-school.2": ("story_01", 2, "lan", "a2e97b3b47d8d480293614ebce75d755c67f4fc08235a33e08cf9141e73cc614", "{pic 0 0}{dialog_up}<>\\p{cls 5}{jump 3}"),
    "to-school.3": ("story_01", 3, "mayl", "7ce8d394a89af47ac7739d041ed3206eb56678830f90590da052b489f8503b80", "{pic 8 0}{dialog_up}<>{d 30}<>\\p{cls 5}{jump 4}"),
    "to-school.4": ("story_01", 4, "lan", "d1d50cde97c69804a72b6849bc378736d071e8dc9500b29c4f40832c2c4385df", "{pic 0 0}{dialog_up}<>\\p{cls 5}{jump 5}"),
    "to-school.5": ("story_01", 5, "mayl", "868d6f70689f714dbafd9384a4f8232a00769111fc7401d061ccc808e8f5a02e", "{pic 8 0}{dialog_up}<>\\p{cls 5}{jump 6}"),
    "to-school.6": ("story_01", 6, "megaman", "9ece152bb04a9540a95e47ffc03158a53bd4e4098135d5427d89bde5e0e5d4e2", "{pic 34 0}{dialog_up}<>\\p{cls 5}{jump 7}"),
    "to-school.7": ("story_01", 7, "lan", "194da28c057df44b2292ef87652fd66757a091aa1f9912bbbc6040ec9b2e72ea", "{pic 0 0}{dialog_up}<>\\p{end 5}"),
    "to-school.8": ("story_01", 8, "mayl", "0d771f54ad40098d466819399b7b27a1b6bba30a9c9a486390bdc3e91827fd09", "{input_off}{fd 160}{pic 8 0}{dialog_up}<>{cls 60}<>{fd 60}{jump 9}"),
    "to-school.9": ("story_01", 9, "lan", "f6a8a94a233586b48689b2dc8bb843f88a5326a9125ef046579d8726a6efa90e", "{pic 0 0}{dialog_up}<>{fd 60}{jump 10}"),
    "to-school.10": ("story_01", 10, "mayl", "f7b918ae008254c75a460efc171aa46776aa03b92c93e69525ba169f7cc26f17", "{pic 8 0}{dialog_up}<>{fd 60}{jump 11}"),
    "to-school.11": ("story_01", 11, "lan", "7a6256328b88e057e805170c8aa031a56df75d76880938e5b8d57da93c51fe46", "{pic 0 0}{dialog_up}<>{fd 60}{jump 12}"),
    "to-school.12": ("story_01", 12, "mayl", "84e117c0ce806e956816dc9c8b438d84baafbc1b540d7b0023087e1f766b0b30", "{pic 8 0}{dialog_up}<>{fd 90}<>{input_on}{end 60}"),
}
# fmt: on

TARGET = "mmbn"


def mmbn_script_archives() -> tuple[MmbnScriptArchive, ...]:
    return ARCHIVES


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts(tuple(_SOURCES))


def mmbn_arabic_sections(
    translations: TranslationSet | None = None,
) -> tuple[MmbnArabicSection, ...]:
    """Every translated section, in the order the morning plays them."""
    texts = _texts(translations)
    return tuple(
        MmbnArabicSection(
            key=key,
            archive=archive,
            index=index,
            speaker=speaker,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (archive, index, speaker, digest, skeleton) in _SOURCES.items()
    )
