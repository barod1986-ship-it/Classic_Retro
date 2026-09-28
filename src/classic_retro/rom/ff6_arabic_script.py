"""Arabic translation of *Final Fantasy III* (USA): the opening, to the end of Narshe.

A new game opens on the cliffs above Narshe: two Imperial soldiers and the
girl they lead in Magitek armour walk into the town, fight their way to the
frozen Esper, and the girl wakes in Arvis's house without her memory; the
guards come, she flees through the mines, and Locke and the Moogles get her
out. The translation takes the messages of those scenes, and the fourteen
characters' names the game writes in them. Every other message stays in
English.

Each original is pinned by its number (what the event script gives the
engine, and what the hooks match) and the SHA-256 of its bytes (its end
included), so the translation can be checked without the ROM and the build
refuses another text. Its command skeleton (``engines.ff6.command_skeleton``:
its commands with their bytes, but the layout) may be pinned too, so the
translation's commands are checked without the ROM as the build checks them
against the ROM's; the build's report carries every original's, for pinning.

The Arabic lives in ``classic_retro/translations/final-fantasy-iii.json``:
logical Unicode Arabic in the engine's notation (``engines.ff6_arabic``): a
line for each page, ``{line}`` where a line must end, ``{Terra}`` and the
other names for the characters' names, and the English's pauses and button
waits as tokens.

The messages are pinned from the ROM (``extract_originals``): numbers 0 (which
shares 1's text) to 63, the Narshe chapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.ff6 import NAMES
from classic_retro.localization.translations import TranslationSet, builtin_translation_set


@dataclass(frozen=True, slots=True)
class Ff6Message:
    """A translated message: its entry, its number, its original's SHA-256 and, when
    pinned, its original's command skeleton."""

    key: str
    number: int
    source_sha256: str
    notation: str
    source_skeleton: tuple[str, ...] | None = None


# key: (the message's number, SHA-256 of its bytes with the end, its commands; None
# until a maintainer pins them from the ROM, as the build's report gives them)
# fmt: off
_SOURCES: dict[str, tuple[int, str, tuple[str, ...] | None]] = {
    "narshe.000": (0, "7597672441a76b09d95ca168a4cd5e33b9e310750fa7d2a969e54fd3956dde57", ('{KeyAfter 18}', '{Key}', '{KeyAfter 18}', '{Key}')),
    "narshe.001": (1, "7597672441a76b09d95ca168a4cd5e33b9e310750fa7d2a969e54fd3956dde57", ('{KeyAfter 18}', '{Key}', '{KeyAfter 18}', '{Key}')),
    "narshe.002": (2, "7a4b795f499318aa92eb39fb36067ec6a36808c979f255d6ad759e7195df368c", ('{KeyAfter 18}', '{Key}')),
    "narshe.003": (3, "f76b8e75fc0d8c3bf5f669bcb62d6ae9a2d1bed25be8968194dfcbebdda8fa44", ('{KeyAfter 18}', '{Key}', '{KeyAfter 18}', '{Key}')),
    "narshe.004": (4, "64658094ceff7f80168789cbdc5f0de306236277bf1f8d31bfad3fd93efbca99", ('{KeyAfter 18}', '{Key}')),
    "narshe.005": (5, "4bfc0413bf55eca36c8ae626a5d89fbcf90e1332f7b8fe04d33c2a981c94873f", ('{KeyAfter 0C}', '{Key}')),
    "narshe.006": (6, "9f64793401ea84d511cc6a380856fa52f727cd346e27eb0e7d068a9712f7c8bb", ('{Pause FF}', '{Key}')),
    "narshe.007": (7, "237462357f60336925522beca77edb1b1f9e204681c029ee411a26da4569ad5e", ('{Pause FF}', '{Key}')),
    "narshe.008": (8, "7d9c4676809cbf1bdceb4fc28d0168830fa8718fed03e4de803526b5210ab0bc", ('{Pause FF}', '{Key}')),
    "narshe.009": (9, "d6106b0c3b02c5c95a9c1cc94e42089b37dcc05b1a25c382368ad1f5e735dc52", ('{Pause 2A}', '{Key}')),
    "narshe.010": (10, "c01a4f2e9a817a4e2b784763aa1841f447ca297ca2fdfaa628fdf6375dda594c", ('{Choice}', '{Choice}')),
    "narshe.011": (11, "a2e63389775c6df84c77a7dd47ead6be288ee06f24bb0b7aafe1575093aa6725", ()),
    "narshe.012": (12, "d921438db2626ca4c3b5361c6ae4bca4a0299d063ff1ad635424e164b4a50306", ()),
    "narshe.013": (13, "e4b7c915c36d4deb59e46130d036cb645c7fdbcc844e71517b43ec8035cc8eae", ()),
    "narshe.014": (14, "1da7d20985656a0d63176d34a38d4036d3565b7f3e5d7984490cc681898e2c13", ()),
    "narshe.015": (15, "7c2af049e5015bf1c83a456c958379c21c638c9f66a1d899c241a812a57f2fc9", ()),
    "narshe.016": (16, "aaa45676aff6a01dac5832ac8868a54269c7ba237148f63186898fb04d16ce2d", ()),
    "narshe.017": (17, "86a4152626f0d227b89c1cd29bd22feecaa87a0215c4537745f66db5dea9a6c9", ()),
    "narshe.018": (18, "81ab13ffb62f5747c4336a8e1654865e49acddf8ae30d271e1b35ef1f4bcb7db", ()),
    "narshe.019": (19, "ddc9e4fc6c48ba21acf74bb735f8344a0b38d84a2807c04291d1d32d764dbed5", ()),
    "narshe.020": (20, "7f460b29f4076142d1f6384ba73d990dba424f9b743fe15ab33069938ddcbab0", ()),
    "narshe.021": (21, "11781184f77a8abccb61f353a5e6ea091da7ba54a8b07b66a7f4845d6f476ab0", ()),
    "narshe.022": (22, "96e90c55f618840233ff866ae2332a8741759cee2d770b75c975986194e1a11d", ()),
    "narshe.023": (23, "67cbbe6e8bc25dd93ef19dcafb83f337a551fec300f874ce1e346895bf2a97c9", ()),
    "narshe.024": (24, "1c3244a003636fabf50407d76d144698e59a87d8e5221c60c2c65b00777af459", ()),
    "narshe.025": (25, "e22ed7fa31abbdd7af0777a48c3fe2f53da9eadb13e850aa0a5df08463454977", ('{Terra}',)),
    "narshe.026": (26, "ec435207f6d3672c51d872d8136fd10b2bb46175fc07dd66cd614a562c45a680", ()),
    "narshe.027": (27, "2aa01c5b49dc0bf9184339359368c161ea7a333485a8491d811fbe9a3c9f1edd", ()),
    "narshe.028": (28, "05edcbbbe55c5b07c1a38dbbd8007b5d339f5f0dfdd4019aa05bd94966e47b8d", ('{Terra}',)),
    "narshe.029": (29, "dd7e617a257c8960a88ed03b9f786dc5547e10f898b27b6759359d77f24f5f50", ()),
    "narshe.030": (30, "49d8770532abd668d2ee0b7b25b31a2fad87005d28e77864967986974a7804ea", ()),
    "narshe.031": (31, "bb65a100a839332bb80a342bede1b5ff90378d6e27c4aeeccd38000f29c240b9", ()),
    "narshe.032": (32, "fd9e6f6fcc0db5a53c03c8daa78fd34c45a335921aeaad86c5bd538258c4803a", ()),
    "narshe.033": (33, "6560da9913801d96eeb98c4d3bf92f0469ad9b1dbf35fd09f05ec77f5a1600b9", ()),
    "narshe.034": (34, "17b27d7eca29fdbf2c6e562f551b0eb92358422fed596fedd2390512103edc02", ()),
    "narshe.035": (35, "7b634eee997e4bbd758db49f13b00d6c6bac1eff68908bb8670580f2d455d007", ()),
    "narshe.036": (36, "f218951f384b9727688c16b3e6ca6f0b99e7fa2288418bc5ef54435c858eac7d", ()),
    "narshe.037": (37, "d415540b988db6637b105a2b3fa5a653be459df8f0862dc891d0b7724d608a8b", ('{Terra}',)),
    "narshe.038": (38, "6d2d8a423cd0afa03444eb712fbd8561e287fa85cbdf2fb0b55181c9b57aa926", ()),
    "narshe.039": (39, "9bb18f075d34d458dd0b11e0091c02c028a8fc2d0fc42dd0a8361873dd01f816", ()),
    "narshe.040": (40, "d033a6f632604d40373a338031706fe15d0b2b664b8f3538047552fee822b661", ()),
    "narshe.041": (41, "50b181fd47c23732e0baee8a413d206461af209d03d0918c0ed05f2976ddba8d", ()),
    "narshe.042": (42, "43bc15a854259620caf500106013f2cb5edaecc761db03f77240e460a993ea07", ('{Locke}', '{Locke}')),
    "narshe.043": (43, "82f6a87a84e2753c87eac0bf3ff88bc370e502f82213ff17e080ef0044064cd5", ('{Locke}',)),
    "narshe.044": (44, "1607e48d8b03a0d058c7b6419446348896bfc71e1cdb270a16e62b3afb76215b", ('{Locke}',)),
    "narshe.045": (45, "0615c8dbd16bbc923feccf447851ec1ec246322ba5d67d8b1df1cb9bbfc3862a", ()),
    "narshe.046": (46, "1ddb42568a51506585567f3e6253b3d2d7e441458e171d11bdae1d89a6b04984", ('{Locke}',)),
    "narshe.047": (47, "235c1372cfdd3c879c36f35232b71909f45f54e7ab11ff564c0dd35f4ff924fc", ()),
    "narshe.048": (48, "d213ba9ca62924fbfa916c7602d2ad633f6c9a9fa10ca012b70fb93c4ba08772", ()),
    "narshe.049": (49, "eda8ba4d54a576d85e1d1ceab0f5697bd8594690200be0b0f642be7ffc5227e2", ()),
    "narshe.050": (50, "143f5faf124e02753a0deb667578982e45ce23423473feb44ff5aaafe3c8de0f", ('{Locke}',)),
    "narshe.051": (51, "4fc738cc51f62881c1f7cca8c03b26b2a37face7256936896d3b27ccdc39f30a", ()),
    "narshe.052": (52, "b7ace062f550244dbcc00c5d59168cc72564cb7bf8a79715d1c74a5114239261", ('{Locke}',)),
    "narshe.053": (53, "c7229dbf72c303dce144e4e9ba5f27d0dd022621b9cc158ee13b68941c205f81", ()),
    "narshe.054": (54, "b3094a0324fd70899cfcc1872baa876cabcd03e2f23e425ec7d9edf235d9b83f", ('{Terra}', '{Choice}', '{Choice}')),
    "narshe.055": (55, "b56f3d6c5820b0d2a98c977ebb48c1335b928b96128bc8de31c34e1a0b399d0b", ('{Terra}',)),
    "narshe.056": (56, "a533c12bd28b4c10255c7b31cd5a607f741ca40034140f8bad2c45a66fe72c76", ('{Terra}',)),
    "narshe.057": (57, "a27f952aa83a9f6eb97684c7870e2544fc788abaed905610a6f09e7152080614", ('{Locke}',)),
    "narshe.058": (58, "80506ed58caf51d4877e5262cef5e121d28574458325a7fa93e665851e484dd0", ('{Locke}',)),
    "narshe.059": (59, "a11a95591262133fcf8542fd54ee580459476d8cf225d5ab8481e9252acb9a79", ('{Locke}',)),
    "narshe.060": (60, "203f85b4f9a1490dedd7496e9ff99ae29da4b8ba7503fad525a93f42b0657539", ('{Terra}', '{Locke}')),
    "narshe.061": (61, "48722972f524b957fcebf59d325a4bc680a8ff4890ee4a1374fa59171626932d", ('{Terra}',)),
    "narshe.062": (62, "56b361d8f518baa10a55c0814ef336fad6130a6fae11cfef5ddefa3739e83030", ('{Locke}',)),
    "narshe.063": (63, "b580bd58e6ecf2e66b8c70aa889c15ebc862608402e98bd3bd656c08985c6848", ('{Terra}', '{Locke}', '{Terra}', '{Locke}')),
}
# fmt: on

TARGET = "final-fantasy-iii"
# The fourteen characters' names, by the name the game's command writes: Terra,
# Locke, Cyan, Shadow, Edgar, Sabin, Celes, Strago, Relm, Setzer, Mog, Gau, Gogo,
# Umaro. The hook draws these in an Arabic message.
NAME_KEYS = tuple(f"name.{name.lower()}" for name in NAMES)


def _texts(translations: TranslationSet | None) -> dict[str, str]:
    return (translations or builtin_translation_set(TARGET)).texts((*_SOURCES, *NAME_KEYS))


def ff6_arabic_messages(translations: TranslationSet | None = None) -> tuple[Ff6Message, ...]:
    """Every translated message, in the order of their numbers."""
    texts = _texts(translations)
    return tuple(
        Ff6Message(key, number, digest, texts[key], skeleton)
        for key, (number, digest, skeleton) in _SOURCES.items()
    )


def ff6_arabic_names(translations: TranslationSet | None = None) -> dict[str, str]:
    """The characters' names in Arabic, by entry (``NAME_KEYS``), in the game's order."""
    texts = _texts(translations)
    return {key: texts[key] for key in NAME_KEYS}
