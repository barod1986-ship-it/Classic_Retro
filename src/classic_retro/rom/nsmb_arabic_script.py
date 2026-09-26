"""Arabic translation of the menus and prompts of *New Super Mario Bros.* (USA).

Every message of the game's three message files: the file select's prompts
(``script/data.bmg``), the world map's menu, save and quit prompts, Star Coin
gates and the secret Challenge mode's greeting (``script/course.bmg``), and the
pause menu and prompts inside a level (``script/game.bmg``): 42 messages.
The level's HUD, the Options screen, the title and the file select's buttons
are pictures, not text, and stay in English.

For each message the original is pinned by its file and index, the SHA-256 of
its UTF-16 text and its escapes and line ends, so the translation can be
checked without the ROM and the ROM build can refuse a different script. A
message's lines are measured against the width its place leaves (``ANSWER``,
``CHOICE`` or ``PROMPT``).

The Arabic lives in ``classic_retro/translations/nsmb.json``: logical Unicode
Arabic in the engine's notation (``engines.nsmb``). It keeps the original's
escapes and line ends, in order: ``{FF:00000100}`` and ``{FF:00000000}``
colour the number ``{01:0100}`` the game writes in (the Star Coins a gate
asks for) and ``{FF:00000200}`` greys a menu choice that cannot be taken.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.nsmb import notation_skeleton, parse_notation
from classic_retro.localization.translations import TranslationSet, builtin_translation_set
from classic_retro.text.bmg import Piece

COURSE = "script/course.bmg"
DATA = "script/data.bmg"
GAME = "script/game.bmg"
# How wide a line may be: the answers of a question stand side by side, a menu
# lists its choices down the middle of its window, and a prompt's lines are
# centred in a window (or the file select's band) of about 230 pixels.
ANSWER = 48
CHOICE = 128
PROMPT = 200


@dataclass(frozen=True, slots=True)
class NsmbArabicMessage:
    key: str
    file: str
    index: int
    line_width: int
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


_COLOURED_NUMBER = "{FF:00000100}{01:0100}{FF:00000000}"

# key: (file, index, line width, SHA-256 of the original, its escapes and line ends)
# fmt: off
_SOURCES: dict[str, tuple[str, int, int, str, str]] = {
    "file_select": (
        DATA, 0, PROMPT, "6c6d2f7964f5f8c15f33c43cd3517f8171a6dadeba806e7acd6f3cd2b4dc4be8", "",
    ),
    "file_copy_from": (
        DATA, 1, PROMPT, "50642e728186e1e826e580badc7867d880d7d4cec466c9b04811f9c72dc5de75", "",
    ),
    "file_copy_to": (
        DATA, 2, PROMPT, "38ec761ea84a451852dea1a2a9d4197305dd2159b6eac8dc597eb3bb6bf75168", "",
    ),
    "file_overwrite": (
        DATA, 3, PROMPT, "6d1f6ac371177435fd48cb8f904e6a58a704e6a55bda70d1995fcfdbcc4be69a", "",
    ),
    "file_copying": (
        DATA, 4, PROMPT, "4c914730fd78fb300a10acc34d635bc19f29679dc799c09a35126d0f693eed27", "",
    ),
    "file_copied": (
        DATA, 5, PROMPT, "15dd8bceb290ee0862028230c2f33972959771f182ca82c52932d306c924ae75", "",
    ),
    "file_erase_select": (
        DATA, 6, PROMPT, "87b717bcca77395a3bdf2a969802e7738b8a8c3e77cd4e99ac8c58f3a42ae6fe", "",
    ),
    "file_erase_confirm": (
        DATA, 7, PROMPT, "2137ac3c4ff22494e162b4f0d1e700dfe824eaaa6b6a3cde7d84afb697a80a5b", "",
    ),
    "file_erasing": (
        DATA, 8, PROMPT, "1b1aab73261b160a7007fec973371147518788b74007402bcf2d412ffdaebc62", "",
    ),
    "file_erased": (
        DATA, 9, PROMPT, "a4035e2fe120e23330841513bcdbfed12a6dde5f1fdf211ec212678c1cec2926", "",
    ),
    "map_yes": (
        COURSE, 0, ANSWER, "448dd611c3dae467dac5c7da79c75a9b6093108f2da7d51bcb1f89d6e5657136", "",
    ),
    "map_no": (
        COURSE, 1, ANSWER, "c7e9c786d36729170adc27baf199ea1e9b3309599ce40b52235e07a3ca6c9f9c", "",
    ),
    "map_continue": (
        COURSE, 2, CHOICE, "31cfae72207c6fd216f19a990ef47886f3a65f63122661d067dbe2e2e8ea21ac", "",
    ),
    "map_save": (
        COURSE, 3, CHOICE, "a7482e25835139b32dfabb85b72e46acb9347f24333650956d9ea790c6653974", "",
    ),
    "map_options": (
        COURSE, 4, CHOICE, "31a126ea7bd4777451221bf652b974b8fb16762067b6bc326c7848fe2790b9b6", "",
    ),
    "map_quit": (
        COURSE, 5, CHOICE, "ee76c377723e6e083c4ab66d2d4bd82a0fd930ce2e5d0884599614fb704ae542", "",
    ),
    "map_gate_spend": (
        COURSE, 6, PROMPT, "5e7ced5a7ac6f03183ab49915caf497a1abc1608b55e747d42f0d041bec7e1ec",
        f"{_COLOURED_NUMBER}\n\n",
    ),
    "map_save_prompt": (
        COURSE, 7, PROMPT, "0053e5615f0ce59c77c296489761d85795d3b8f527b79043c2f3d62426738e43", "",
    ),
    "map_quit_prompt": (
        COURSE, 8, PROMPT, "76d05e270c2dd78af9a39531f0a6a38806e56970f35cfa27220ff45bf4bae459", "\n",
    ),
    "map_lose_data": (
        COURSE, 9, PROMPT, "2f58105a4d57833f2e799f09c6e5c7e5d48626098db78059d90eaef0acb0e5b0", "\n",
    ),
    "map_gate_short": (
        COURSE, 10, PROMPT, "e8aba74bad08bbd771d51cb3b7b2a43a9cefa00c5ebdab446aad5285cc29fc8d",
        f"\n{_COLOURED_NUMBER}\n",
    ),
    "map_saving": (
        COURSE, 11, PROMPT, "970c9243406deac88820ee41481175d67a3ef0861b31c5a34959f92dd4a7420d", "",
    ),
    "map_saved": (
        COURSE, 12, PROMPT, "758ac39fec8aed9b775d3d15eb69023776905db5200d0f2a9d4fc5e6ba7411f5", "",
    ),
    "map_menu_save": (
        COURSE, 13, CHOICE, "d02596db6cff4d92ccdd610b0fd7db33c1034496029981243771c53f3ff52aa2",
        "\n\n\n",
    ),
    "map_menu": (
        COURSE, 14, CHOICE, "e6321795e8e1abaec6892b06c13484f182ec79071efd8faebc8df9ecd8707aed",
        "\n\n",
    ),
    "challenge_mode": (
        COURSE, 15, PROMPT, "7598c63fdbc7183ad36aca7f2abc905e7dd96b4648aad0fd1f341bacbf863bd7",
        "\n\n\n\n",
    ),
    "level_yes": (
        GAME, 0, ANSWER, "448dd611c3dae467dac5c7da79c75a9b6093108f2da7d51bcb1f89d6e5657136", "",
    ),
    "level_no": (
        GAME, 1, ANSWER, "c7e9c786d36729170adc27baf199ea1e9b3309599ce40b52235e07a3ca6c9f9c", "",
    ),
    "level_continue": (
        GAME, 2, CHOICE, "31cfae72207c6fd216f19a990ef47886f3a65f63122661d067dbe2e2e8ea21ac", "",
    ),
    "level_options": (
        GAME, 3, CHOICE, "31a126ea7bd4777451221bf652b974b8fb16762067b6bc326c7848fe2790b9b6", "",
    ),
    "level_quit": (
        GAME, 4, CHOICE, "ee76c377723e6e083c4ab66d2d4bd82a0fd930ce2e5d0884599614fb704ae542", "",
    ),
    "level_save_prompt": (
        GAME, 5, PROMPT, "0053e5615f0ce59c77c296489761d85795d3b8f527b79043c2f3d62426738e43", "",
    ),
    "level_no_save": (
        GAME, 6, PROMPT, "034156934951e80c5f3a73812176faae2e2c87874acddd88a95fa4bff2784816", "\n",
    ),
    "level_sure": (
        GAME, 7, PROMPT, "9aaf817ff0511c9be74e2a37d03d75589426a34e575221a5913c3fe87243e2ce", "",
    ),
    "level_saving": (
        GAME, 8, PROMPT, "970c9243406deac88820ee41481175d67a3ef0861b31c5a34959f92dd4a7420d", "",
    ),
    "level_saved": (
        GAME, 9, PROMPT, "758ac39fec8aed9b775d3d15eb69023776905db5200d0f2a9d4fc5e6ba7411f5", "",
    ),
    "pause_menu_locked": (
        GAME, 10, CHOICE, "82725f46cb20363ab91366b33443f637bfb824e4f7af3dedec2f41909fb65e16",
        "\n{FF:00000200}\n{FF:00000000}\n",
    ),
    "pause_menu": (
        GAME, 11, CHOICE, "d1283ab84158f2f9251d3a7648ec56d13d57aaf90bdf33633100719d009e56bf",
        "\n\n\n",
    ),
    "pause_menu_short": (
        GAME, 12, CHOICE, "6ef4d730e181554d33a4f6966a38fcd9a74a6da324937fbcca0768a00191f879", "\n",
    ),
    "level_gate_spend": (
        GAME, 13, PROMPT, "e5e270163bd36a1b3d85bb308fbb76edfb5c4a15a9d796d0e8446475f9dd91aa",
        f"\n{_COLOURED_NUMBER}",
    ),
    "level_gate_short": (
        GAME, 14, PROMPT, "bdbee1ccf17a526d4fadef64194254573203e0e1accfd24f874b171534f8fd14",
        f"\n{_COLOURED_NUMBER}",
    ),
    "stuck_hint": (
        GAME, 15, PROMPT, "757163d66c66b7b4e52441fe72d10419f81c5075ff1db29e92eb20f33a87715a",
        "\n\n",
    ),
}
# fmt: on

TARGET = "nsmb"


def nsmb_arabic_messages(
    translations: TranslationSet | None = None,
) -> tuple[NsmbArabicMessage, ...]:
    """Every translated message: the file select's, the world map's, then a level's."""
    texts = (translations or builtin_translation_set(TARGET)).texts(_SOURCES)
    return tuple(
        NsmbArabicMessage(
            key=key,
            file=file,
            index=index,
            line_width=width,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
        )
        for key, (file, index, width, digest, skeleton) in _SOURCES.items()
    )
