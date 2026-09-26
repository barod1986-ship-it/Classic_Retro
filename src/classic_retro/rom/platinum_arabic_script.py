"""Arabic translation of the *Pokémon Platinum* (USA) new-game intro.

A new game opens with Professor Rowan: his welcome, the choice of control
info, adventure info or no info, the pages he shows for each, the Poké Ball
the player opens on the touch screen, his words on Pokémon, then the player's
gender and name, the rival's name and his farewell. That is the whole text
bank ``TEXT_BANK_ROWAN_INTRO`` (bank 389 of ``/msgdata/pl_msg.narc``): 45
strings, of which this script translates 37:

- the dialogue in the message box, 2 rows of 216 pixels, typed a letter at a
  time: ``\\r`` waits for A and starts a new page, ``\\f`` waits and scrolls
  a row, ``{YESNO 0}`` shows the touch-screen icon at the box's edge;
- the pages of control and adventure info, shown at once on the screen. The
  control pages' window starts beside the buttons' pictures and reaches the
  screen's right edge; the overlay narrows it to 22 tiles (176 pixels), so
  right-aligned lines keep a margin. The pages on the buttons keep the
  original's rows (``fixed_rows``): each row sits beside a button's picture.
  The adventure pages' window is 24 tiles (192 pixels);
- the menus' entries: the info choices, Yes and No, and "New name!".

String 6 is the touch-screen icon alone, the example the control pages point
to: its translation adds a space of the Arabic font, so the line is right to
left and the icon sits at the box's left edge, as in the Arabic messages.

Left in English: the rival's names 37 to 44. The one chosen becomes the
rival's name for the rest of the game, which is in English; in the Arabic menu
they are drawn left to right, at its right edge.

The intro ends on a television: Rowan's comment, shown at once in white and
centred on the screen, before the game starts in the player's room. That is
the only string of ``TEXT_BANK_ROWAN_INTRO_TV_APP`` (bank 607), the 38th of
this script.

For each string the original is pinned by its bank and index, the SHA-256 of its
16-bit codes (without the final ``FFFF``) and its commands, so the
translation can be checked without the ROM and the ROM build can refuse a
different script.

The Arabic lives in ``classic_retro/translations/platinum.json``: logical
Unicode Arabic in the engine's notation (``engines.pokemon_gen4``). It keeps
every command of the original, in order: the breaks ``\\r`` and ``\\f``, the
names (``{STRVAR_1 3, 0, 0}`` the player's, ``{STRVAR_1 3, 1, 0}`` the
rival's) and ``{YESNO 0}``. Line ends after text (``\\n``) may move.
"""

from __future__ import annotations

from dataclasses import dataclass

from classic_retro.engines.pokemon_gen4 import Piece, notation_skeleton, parse_notation
from classic_retro.engines.pokemon_gen4_arabic import Gen4Window
from classic_retro.localization.translations import TranslationSet, builtin_translation_set

MESSAGE_ARCHIVE = "msgdata/pl_msg.narc"
ROWAN_INTRO = 389
ROWAN_INTRO_TV = 607
# Each bank's strings, as the pinned image holds them.
BANK_STRINGS = {ROWAN_INTRO: 45, ROWAN_INTRO_TV: 1}

# The windows of the intro (rowan_intro_app.c): the message box and the info
# pages print from their left edge; a menu prints its entries 12 pixels in.
DIALOGUE = Gen4Window("dialogue", 27 * 8, 2)
# The control pages' window, 22 tiles wide once the overlay narrows it (it
# reaches the screen's right edge at 24), and the adventure pages', 24.
CONTROL_INFO = Gen4Window("block", 22 * 8, 12)
INFO = Gen4Window("block", 24 * 8, 12)
INFO_CHOICES = Gen4Window("menu", 16 * 8, 1, text_x=12)
YES_NO = Gen4Window("menu", 6 * 8, 1, text_x=12)
RIVAL_NAMES = Gen4Window("menu", 14 * 8, 1, text_x=12)
# The television's screen (tv_app.c): the text is centred as a block.
TELEVISION = Gen4Window("block", 32 * 8, 12)


@dataclass(frozen=True, slots=True)
class PlatinumArabicString:
    key: str
    bank: int
    index: int
    window: Gen4Window
    source_sha256: str
    source_skeleton: tuple[str, ...]
    notation: str
    # The original's rows, which the translation keeps (blank rows included).
    fixed_rows: tuple[bool, ...] | None = None

    @property
    def pieces(self) -> tuple[Piece, ...]:
        return parse_notation(self.notation)


# key: (index, window, SHA-256 of the original, its commands, its rows: "x" text, "." blank)
# in the intro's bank; the television's string follows.
# fmt: off
_SOURCES: dict[str, tuple[int, Gen4Window, str, str, str | None]] = {
    "hello_there": (
        0, DIALOGUE,
        "993fdd49bbb4c880cee2d01dfdd1f456d41226c52662c77f04f23d2b7dd8f9e9", "\r\r", None,
    ),
    "my_name_is_rowan": (
        1, DIALOGUE,
        "e09c499bf03a62f659b3678d37356c23da3c9976cf48c46ab58ac94dd13aa356", "\r\r\r\r", None,
    ),
    "control_info_buttons": (
        2, CONTROL_INFO,
        "f038c3df94ad7fe21ec7960d149038ddf184952b727a9367b523a1946b7824b2", "\n\n", "xxx.xx.xx",
    ),
    "control_info_xy": (
        3, CONTROL_INFO,
        "db5d504fb93297b72d5f11382e1085fdc03f2c3e5330e9582eb80d3b41be9744", "\n", "x.xxx",
    ),
    "control_info_touch_screen": (
        4, CONTROL_INFO,
        "aa554c971e6e943b5fc7477b064925a114344f80f2fc45c34606772d800f5a6d", "\n", None,
    ),
    "control_info_mark": (
        5, CONTROL_INFO,
        "fcfef97fe9423c043fdd5ef3c5f260addb74424311c52ba769de31f46f340c34", "", None,
    ),
    "control_info_icon": (
        6, DIALOGUE,
        "df994fa5b9e9787dd69eba11394911baad2857e29ca95b501bcce9a3edc3f75d", "{YESNO 0}", None,
    ),
    "control_info_understood": (
        7, DIALOGUE,
        "6ed79db47dcb473aceff259dcdfc31774a18bf1314f65e46239daf11862ccb1e", "{YESNO 0}", None,
    ),
    "control_info_use_touch_screen": (
        8, DIALOGUE,
        "b6dcaab1412b4f872a1d05c89bc00006c2d29c8235edf98a33f174ce57f7d833", "{YESNO 0}", None,
    ),
    "anything_else": (
        9, DIALOGUE,
        "f088423905e25420f1fbd5e6472404f4527a80f715d7ee22dde6b08238f00ec3", "\r", None,
    ),
    "adventure_info_world": (
        10, INFO,
        "96c285329be8e519d978ca623601a6fe874b0bc590b0fa4a529a73c9c06e927d", "", None,
    ),
    "adventure_info_speak": (
        11, INFO,
        "606a69440fd6cee451ad326bd99ac6a81b529ce41d7cc8d1c3c244acb04dd62d", "", None,
    ),
    "adventure_info_paths": (
        12, INFO,
        "f5643048b5d8073ee353d87b80a7459d953f1d9772179b4004c4450ac24505ba", "", None,
    ),
    "adventure_info_battles": (
        13, INFO,
        "6cef6f1cb31e6fc464b39ee0d6261b97506e9d695aaa5288ed1c2234002460e5", "\n", None,
    ),
    "adventure_info_power": (
        14, INFO,
        "c399367cdf147db4f8d81a574aef5939b9a6469255d52ac4e0ef0dcbc99c4b3d", "", None,
    ),
    "adventure_info_growth": (
        15, INFO,
        "0995a6a98620400a98dd8969f430909d96980e8f0d82991494a1ade86d312167", "\n", None,
    ),
    "widely_inhabited": (
        16, DIALOGUE,
        "07d780e4f542c4959ab1fdd9f43e31e420092e1196c5b3a19b2149d8d237e435", "\r", None,
    ),
    "have_poke_ball": (
        17, DIALOGUE,
        "95bcd178f911a9001ff9460191f9a06257ab06ca2fcf780771bf969d70f92889", "\r{YESNO 0}", None,
    ),
    "poke_ball_use_touch_screen": (
        18, DIALOGUE,
        "8a6ea7c7039d7c4339a006442b7e64972626f5f150dbbb651a090e75887393da", "{YESNO 0}", None,
    ),
    "live_alongside_pokemon": (
        19, DIALOGUE,
        "4046ef7444d23327dab92b7f45cbbae46aad2f34a1ae28d61ad9d44c5ee35efa", "\r\f\r\f\r\r\r",
        None,
    ),
    "about_yourself": (
        20, DIALOGUE,
        "aec7a7c022230aa5277a8705fa348882e4d9ad471b65e085667c642be7f1305f", "\r", None,
    ),
    "boy_or_girl": (
        21, DIALOGUE,
        "b3f3247a3e52dcca368998a36a9fc5dd55eda4e9a4ad15cbcb48533fd7d7b1b2", "\r", None,
    ),
    "confirm_boy": (
        22, DIALOGUE,
        "c4e71bcaec81243436c5aa5865ce520fa1f69afad0a98ae0dfe4a47de2a59564", "\r", None,
    ),
    "confirm_girl": (
        23, DIALOGUE,
        "8d83b982fdf68cdfbb0a51a1768bfb070f338be9bc50b8992d5a9dbb993b037f", "\r", None,
    ),
    "what_is_your_name": (
        24, DIALOGUE,
        "fb3c6d58e4d167377370a26e180222638a7e0cb5b3bbf9f182349e66bdeda1fe", "\r", None,
    ),
    "confirm_name_boy": (
        25, DIALOGUE,
        "00cf98f7993ab1ca13cc845d090bf6f7dfed7f10620b0eb71edef5acbc650e45",
        "{STRVAR_1 3, 0, 0}\r", None,
    ),
    "confirm_name_girl": (
        26, DIALOGUE,
        "00cf98f7993ab1ca13cc845d090bf6f7dfed7f10620b0eb71edef5acbc650e45",
        "{STRVAR_1 3, 0, 0}\r", None,
    ),
    "so_you_are": (
        27, DIALOGUE,
        "a7b1019815d7675eee7bab6fa73f01676b3d4f33bc5b246fad0b8ff3b008ad4f",
        "{STRVAR_1 3, 0, 0}\r\r\r", None,
    ),
    "rival_name_question": (
        28, DIALOGUE,
        "fb57e8d428b7cb15b6fd3b822cdfff06f7b29e7c55dee1fd3bb03e40ca9488c7", "\r", None,
    ),
    "confirm_rival_name": (
        29, DIALOGUE,
        "04fb60b8647152e336adc92d9dc211cec924c38bdfe13a044a989954bf71286c",
        "{STRVAR_1 3, 1, 0}\r", None,
    ),
    "farewell": (
        30, DIALOGUE,
        "8f0e43f4abf281a85761af3f599484edd7a15af622cc082e919222c4282618ce",
        "{STRVAR_1 3, 0, 0}\r\r\r\f\r\r", None,
    ),
    "choice_control_info": (
        31, INFO_CHOICES,
        "2d7292accf8c0eaacbdc4c64e86ca3bbb368ac1701cdb6042280b6878c6d4781", "", None,
    ),
    "choice_adventure_info": (
        32, INFO_CHOICES,
        "1a0502c2e99e0968ed9af0ef2ceb32b224b7b62527eff691b0d15a883f621da4", "", None,
    ),
    "choice_no_info": (
        33, INFO_CHOICES,
        "f19e3197ca181bf53d840e49409fb7b7befc07b7193d6dbdb953b485e6984b20", "", None,
    ),
    "choice_yes": (
        34, YES_NO,
        "a7e27e4673ca5c5070d83173e82a00e7adc7153e74c7a1befcd0f4127453abf3", "", None,
    ),
    "choice_no": (
        35, YES_NO,
        "ed01a57eab4986966d90387effcd68d0ba4273857dd64a6f07b46fb94cefb494", "", None,
    ),
    "choice_new_rival_name": (
        36, RIVAL_NAMES,
        "0a656e8111fb1a3f042220f2ece9325bb5d1ce16ec8cee8fb1ed4c0cf571f3d8", "", None,
    ),
}
_TV_SOURCES: dict[str, tuple[int, Gen4Window, str, str, str | None]] = {
    "television_comment": (
        0, TELEVISION,
        "7ea2084d3b4c5e9ad9539eddde953185eae790e6342e9d128a5deca3f5e5748e", "\n", None,
    ),
}
# fmt: on

TARGET = "platinum"


def platinum_arabic_strings(
    translations: TranslationSet | None = None,
) -> tuple[PlatinumArabicString, ...]:
    """Every translated string, in the order the game shows its banks."""
    sources = {
        key: (bank, *source)
        for bank, table in ((ROWAN_INTRO, _SOURCES), (ROWAN_INTRO_TV, _TV_SOURCES))
        for key, source in table.items()
    }
    texts = (translations or builtin_translation_set(TARGET)).texts(tuple(sources))
    return tuple(
        PlatinumArabicString(
            key=key,
            bank=bank,
            index=index,
            window=window,
            source_sha256=digest,
            source_skeleton=notation_skeleton(parse_notation(skeleton)),
            notation=texts[key],
            fixed_rows=None if rows is None else tuple(row == "x" for row in rows),
        )
        for key, (bank, index, window, digest, skeleton, rows) in sources.items()
    )
