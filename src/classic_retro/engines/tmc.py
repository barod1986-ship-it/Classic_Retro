"""The Legend of Zelda: The Minish Cap (GBA) text engine.

The zeldaret/tmc decompilation stores the USA script as ``translations/USA.json``:
a list of text tables, each a list of strings written in the notation of its
``tmc_strings`` packer. This module parses that notation into Classic Retro
tokens and renders tokens back into it.

Byte-level facts used here come from the decompilation (``src/text.c``
``GetCharacter`` and ``tools/src/tmc_strings``):

- ``00`` ends a string, ``0A`` starts the next line of the two-line dialogue box;
- ``01 xx`` message flag, ``02 cc`` colour, ``03 hh ll`` sound, ``04 xx [yy]``
  window/render controls, ``05`` choice, ``06 nn`` runtime variable,
  ``07 tt ii`` continue with text ``ttii``, ``08 xx`` delay, ``09 xx`` auto-advance,
  ``0C kk`` key icon, ``0F ss`` symbol glyph;
- other bytes are glyphs from the font page selected by the byte value.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Mapping

from classic_retro.adapters.base import EngineAdapter
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    Token,
    TokenKind,
    TokenMovement,
    TokenStream,
)

TMC_COLORS = ("White", "Red", "Green", "Blue", "Yellow")
TMC_KEYS = ("A", "B", "Left", "Right", "DUp", "DDown", "DLeft", "DRight", "Dpad", "Select", "Start")

# tmc_strings CharConvertArray (USA/EU glyph bytes >= 0x20).
_ASCII = {code: chr(code) for code in range(0x20, 0x7B) if code != 0x5C}
_EXTENDED = {
    0x82: ",",
    0x84: "„",
    0x85: "⋯",
    0x8A: "Š",
    0x8B: "‹",
    0x8C: "Œ",
    0x8E: "Ž",
    0x91: "‘",
    0x92: "’",
    0x93: "“",
    0x94: "”",
    0x95: "·",
    0x99: "™",
    0x9A: "š",
    0x9B: "›",
    0x9C: "œ",
    0x9E: "ž",
    0x9F: "Ÿ",
    0xA1: "¡",
    0xA3: "♪",
    0xAA: "ª",
    0xAB: "«",
    0xB0: "º",
    0xB7: "´",
    0xBB: "»",
    0xBF: "¿",
}
_EXTENDED.update({code: chr(code) for code in range(0xC0, 0x100) if code != 0xD0})
_EXTENDED[0xD0] = "Đ"
TMC_GLYPH_BYTES: Mapping[int, str] = dict(sorted({**_ASCII, **_EXTENDED}.items()))
# tmc_strings packs a character as the lowest byte that renders it (',' is 0x2C, not 0x82).
_BYTES_BY_CHARACTER: dict[str, int] = {}
for _code, _character in TMC_GLYPH_BYTES.items():
    _BYTES_BY_CHARACTER.setdefault(_character, _code)

# Characters that may be written literally inside a tmc_strings JSON string.
# Braces start a command; everything else in the table round-trips.
_LITERAL_SAFE = frozenset(character for character in _BYTES_BY_CHARACTER if character not in "{}")

_COMMAND = re.compile(r"\{([^{}]*)\}")
_HEX_COMMAND = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2})*$")

TMC_DIALOGUE_LINE_WIDTH = 0xD0
TMC_PLAYER_NAME_LENGTH = 6


class TmcEngineAdapter(EngineAdapter):
    id = "gba.tmc"
    display_name = "The Legend of Zelda: The Minish Cap text engine"
    platform_ids = ("gba",)


def tmc_line(token_id: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=TokenKind.LINE_BREAK,
        movement=TokenMovement.ORDERED,
        args={"tmc": "\n"},
    )


def tmc_color(token_id: str, color: str) -> InlineToken:
    if color not in TMC_COLORS:
        raise ValueError(f"Unknown Minish Cap text colour: {color}")
    return _command(token_id, TokenKind.CONTROL, "COLOR", f"{{Color:{color}}}")


def tmc_sound(token_id: str, high: int, low: int) -> InlineToken:
    return _command(token_id, TokenKind.CONTROL, "SOUND", f"{{Sound:{high:02X}:{low:02X}}}")


def tmc_player(token_id: str) -> InlineToken:
    return _command(token_id, TokenKind.VARIABLE, "PLAYER", "{Player}")


def tmc_jump(token_id: str, table: int, index: int) -> InlineToken:
    return _command(token_id, TokenKind.CONTROL, "CONTINUE_TEXT", f"{{07:{table:02X}:{index:02X}}}")


def tmc_raw(token_id: str, notation: str, name: str = "CONTROL") -> InlineToken:
    return _command(token_id, TokenKind.CONTROL, name, notation)


def _command(token_id: str, kind: TokenKind, name: str, notation: str) -> InlineToken:
    return InlineToken(
        id=token_id,
        kind=kind,
        movement=TokenMovement.ORDERED,
        name=name,
        args={"tmc": notation},
    )


def token_notation(token: InlineToken) -> str:
    notation = token.args.get("tmc")
    if not isinstance(notation, str):
        raise ClassicRetroError(
            ErrorCode.UNENCODABLE_TOKEN,
            f"Minish Cap token {token.id} has no tmc_strings notation",
        )
    return notation


def parse_tmc_string(text: str, *, id_prefix: str = "t", glyph_text: bool = True) -> TokenStream:
    """Parse one tmc_strings JSON string into text and ordered engine tokens.

    ``glyph_text=False`` reads a translation, whose text the Arabic encoder maps
    later: any character is text there.
    """
    output: list[Token] = []
    buffer: list[str] = []
    index = 0
    counter = 0

    def flush() -> None:
        if buffer:
            output.append(TextToken("".join(buffer)))
            buffer.clear()

    while index < len(text):
        character = text[index]
        if character == "\n":
            flush()
            output.append(tmc_line(f"{id_prefix}{counter}"))
            counter += 1
            index += 1
            continue
        if character == "{":
            match = _COMMAND.match(text, index)
            if match is None:
                raise ClassicRetroError(
                    ErrorCode.UNSUPPORTED_CONTROL_CODE,
                    f"Unterminated Minish Cap command at {index}: {text[index : index + 16]!r}",
                )
            flush()
            output.append(_parse_command(match.group(0), match.group(1), f"{id_prefix}{counter}"))
            counter += 1
            index = match.end()
            continue
        if glyph_text and character not in _BYTES_BY_CHARACTER:
            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TEXT,
                f"Minish Cap text has no glyph byte for {character!r}",
            )
        buffer.append(character)
        index += 1

    flush()
    return TokenStream(tuple(output))


def _parse_command(notation: str, body: str, token_id: str) -> InlineToken:
    name, _, argument = body.partition(":")
    if name == "Color" and argument in TMC_COLORS:
        return _command(token_id, TokenKind.CONTROL, "COLOR", notation)
    if name == "Sound":
        return _command(token_id, TokenKind.CONTROL, "SOUND", notation)
    if name == "Player":
        return _command(token_id, TokenKind.VARIABLE, "PLAYER", notation)
    if name == "Var":
        return _command(token_id, TokenKind.VARIABLE, f"VAR_{argument}", notation)
    if name == "Choice":
        return _command(token_id, TokenKind.CONTROL, "CHOICE", notation)
    if name == "Key" and argument in TMC_KEYS:
        return _command(token_id, TokenKind.CONTROL, "KEY_ICON", notation)
    if name == "Symbol":
        return _command(token_id, TokenKind.CONTROL, "SYMBOL", notation)
    if _HEX_COMMAND.match(body):
        values = bytes.fromhex(body.replace(":", ""))
        label = {
            0x01: "MESSAGE_FLAG",
            0x04: "RENDER_CONTROL",
            0x07: "CONTINUE_TEXT",
            0x08: "DELAY",
            0x09: "AUTO_ADVANCE",
        }.get(values[0], f"CONTROL_{values[0]:02X}")
        return _command(token_id, TokenKind.CONTROL, label, notation)
    raise ClassicRetroError(
        ErrorCode.UNSUPPORTED_CONTROL_CODE,
        f"Unknown Minish Cap command {notation}",
    )


def render_tmc_string(stream: TokenStream, *, glyph_text: bool = True) -> str:
    """Render tokens as a tmc_strings JSON string (glyph text must be TMC characters).

    ``glyph_text=False`` writes a translation's notation, whose text may be anything.
    """
    parts: list[str] = []
    for token in stream.tokens:
        if isinstance(token, TextToken):
            for character in token.text:
                if glyph_text and character not in _LITERAL_SAFE:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TEXT,
                        f"Minish Cap text has no glyph byte for {character!r}",
                    )
            parts.append(token.text)
        else:
            parts.append(token_notation(token))
    return "".join(parts)


def control_signature(stream: TokenStream) -> tuple[str, ...]:
    """Engine commands that a translation must preserve (colours may move, lines may change)."""
    return tuple(
        token_notation(token)
        for token in stream.tokens
        if isinstance(token, InlineToken)
        and token.kind is not TokenKind.LINE_BREAK
        and token.name not in {"COLOR"}
    )


def glyph_advance(glyph_half_rows: bytes) -> int:
    """Width encoded in a glyph half's first row: leading 0xF nibbles skip, others count."""
    word = struct.unpack_from("<I", glyph_half_rows, 0)[0]
    mask = 0xF
    index = 0
    while index < 8 and word & mask == mask:
        mask <<= 4
        index += 1
    start = index
    while index < 8 and word & mask != mask:
        mask <<= 4
        index += 1
    return index - start


def latin_glyph_widths(font_page: bytes, extension_page: bytes | None = None) -> dict[str, int]:
    """Advance widths of the USA Latin font (page 1 and the 0x80+ extension page)."""
    widths: dict[str, int] = {}
    for character, code in _BYTES_BY_CHARACTER.items():
        if code < 0x80:
            offset = code * 64
            source = font_page
        else:
            if extension_page is None:
                continue
            offset = (code - 0x80) * 64
            source = extension_page
        if offset + 64 <= len(source):
            widths[character] = glyph_advance(source[offset : offset + 64])
    return widths
