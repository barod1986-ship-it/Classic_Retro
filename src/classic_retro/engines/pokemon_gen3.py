from __future__ import annotations

from classic_retro.adapters.base import EngineAdapter
from classic_retro.codec.base import DecodedMessage, GameTextCodec
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import (
    InlineToken,
    TextToken,
    Token,
    TokenKind,
    TokenMovement,
    TokenStream,
)

_EOS = 0xFF
_NEWLINE = 0xFE
_PLACEHOLDER = 0xFD
_EXT_CTRL = 0xFC
_PROMPT_CLEAR = 0xFB
_PROMPT_SCROLL = 0xFA
_EXTRA_SYMBOL = 0xF9
_KEYPAD_ICON = 0xF8
_DYNAMIC = 0xF7

_GLYPHS: dict[int, str] = {
    0x00: " ",
    0x01: "À",
    0x02: "Á",
    0x03: "Â",
    0x04: "Ç",
    0x05: "È",
    0x06: "É",
    0x07: "Ê",
    0x08: "Ë",
    0x09: "Ì",
    0x0B: "Î",
    0x0C: "Ï",
    0x0D: "Ò",
    0x0E: "Ó",
    0x0F: "Ô",
    0x10: "Œ",
    0x11: "Ù",
    0x12: "Ú",
    0x13: "Û",
    0x14: "Ñ",
    0x15: "ß",
    0x16: "à",
    0x17: "á",
    0x19: "ç",
    0x1A: "è",
    0x1B: "é",
    0x1C: "ê",
    0x1D: "ë",
    0x1E: "ì",
    0x20: "î",
    0x21: "ï",
    0x22: "ò",
    0x23: "ó",
    0x24: "ô",
    0x25: "œ",
    0x26: "ù",
    0x27: "ú",
    0x28: "û",
    0x29: "ñ",
    0x2A: "º",
    0x2B: "ª",
    0x2D: "&",
    0x2E: "+",
    0x35: "=",
    0x36: ";",
    0x51: "¿",
    0x52: "¡",
    0x5A: "Í",
    0x5B: "%",
    0x5C: "(",
    0x5D: ")",
    0x68: "â",
    0x6F: "í",
    0x85: "<",
    0x86: ">",
    0xA1: "0",
    0xA2: "1",
    0xA3: "2",
    0xA4: "3",
    0xA5: "4",
    0xA6: "5",
    0xA7: "6",
    0xA8: "7",
    0xA9: "8",
    0xAA: "9",
    0xAB: "!",
    0xAC: "?",
    0xAD: ".",
    0xAE: "-",
    0xAF: "·",
    0xB0: "…",
    0xB1: "“",
    0xB2: "”",
    0xB3: "‘",
    0xB4: "’",
    0xB5: "♂",
    0xB6: "♀",
    0xB7: "¥",
    0xB8: ",",
    0xB9: "×",
    0xBA: "/",
    0xF0: ":",
}
_GLYPHS.update({0xBB + index: chr(ord("A") + index) for index in range(26)})
_GLYPHS.update({0xD5 + index: chr(ord("a") + index) for index in range(26)})
_BYTES_BY_GLYPH = {value: key for key, value in _GLYPHS.items()}

_PLACEHOLDERS = {
    0x01: "PLAYER",
    0x02: "STRING_VAR_1",
    0x03: "STRING_VAR_2",
    0x04: "STRING_VAR_3",
    0x05: "KUN",
    0x06: "RIVAL",
    0x07: "VERSION",
    0x08: "MAGMA",
    0x09: "AQUA",
    0x0A: "MAXIE",
    0x0B: "ARCHIE",
    0x0C: "GROUDON",
    0x0D: "KYOGRE",
}

_EXTENDED_CONTROLS: dict[int, tuple[str, int]] = {
    0x01: ("COLOR", 1),
    0x02: ("HIGHLIGHT", 1),
    0x03: ("SHADOW", 1),
    0x04: ("COLOR_HIGHLIGHT_SHADOW", 3),
    0x05: ("PALETTE", 1),
    0x06: ("FONT", 1),
    0x07: ("RESET_FONT", 0),
    0x08: ("PAUSE", 1),
    0x09: ("PAUSE_UNTIL_PRESS", 0),
    0x0A: ("WAIT_SE", 0),
    0x0B: ("PLAY_BGM", 2),
    0x0C: ("ESCAPE", 1),
    0x0D: ("SHIFT_RIGHT", 1),
    0x0E: ("SHIFT_DOWN", 1),
    0x0F: ("FILL_WINDOW", 0),
    0x10: ("PLAY_SE", 2),
    0x11: ("CLEAR", 1),
    0x12: ("SKIP", 1),
    0x13: ("CLEAR_TO", 1),
    0x14: ("MIN_LETTER_SPACING", 1),
    0x15: ("JPN", 0),
    0x16: ("ENG", 0),
    0x17: ("PAUSE_MUSIC", 0),
    0x18: ("RESUME_MUSIC", 0),
}


class PokemonGen3EngineAdapter(EngineAdapter):
    id = "gba.pokemon-gen3"
    display_name = "Pokémon Generation III text engine"
    platform_ids = ("gba",)

    def text_codec(self) -> PokemonGen3TextCodec:
        return PokemonGen3TextCodec()


class PokemonGen3TextCodec(GameTextCodec):
    def decode(self, data: bytes, *, require_terminator: bool = False) -> DecodedMessage:
        output: list[Token] = []
        buffer: list[str] = []
        offset = 0

        def flush() -> None:
            if buffer:
                output.append(TextToken("".join(buffer)))
                buffer.clear()

        while offset < len(data):
            value = data[offset]

            if value == _EOS:
                flush()
                return DecodedMessage(
                    stream=TokenStream(tuple(output)),
                    consumed_bytes=offset + 1,
                    terminator_id="eos",
                )

            if value == _NEWLINE:
                flush()
                output.append(
                    InlineToken(
                        id=f"line_{offset:06x}",
                        kind=TokenKind.LINE_BREAK,
                        movement=TokenMovement.ORDERED,
                    )
                )
                offset += 1
                continue

            if value in {_PROMPT_CLEAR, _PROMPT_SCROLL}:
                flush()
                name = "PROMPT_CLEAR" if value == _PROMPT_CLEAR else "PROMPT_SCROLL"
                output.append(_control(offset, name, bytes([value])))
                offset += 1
                continue

            if value == _PLACEHOLDER:
                _require(data, offset, 2, "placeholder")
                flush()
                placeholder_id = data[offset + 1]
                output.append(
                    InlineToken(
                        id=f"placeholder_{offset:06x}",
                        kind=TokenKind.VARIABLE,
                        movement=TokenMovement.FREE,
                        name=_PLACEHOLDERS.get(
                            placeholder_id,
                            f"PLACEHOLDER_{placeholder_id:02X}",
                        ),
                        args={"raw_hex": data[offset : offset + 2].hex()},
                    )
                )
                offset += 2
                continue

            if value == _DYNAMIC:
                _require(data, offset, 2, "dynamic placeholder")
                flush()
                dynamic_id = data[offset + 1]
                output.append(
                    InlineToken(
                        id=f"dynamic_{offset:06x}",
                        kind=TokenKind.VARIABLE,
                        movement=TokenMovement.FREE,
                        name=f"DYNAMIC_{dynamic_id:02X}",
                        args={"raw_hex": data[offset : offset + 2].hex()},
                    )
                )
                offset += 2
                continue

            if value == _EXT_CTRL:
                _require(data, offset, 2, "extended control")
                code = data[offset + 1]
                spec = _EXTENDED_CONTROLS.get(code)
                if spec is None:
                    raise ClassicRetroError(
                        ErrorCode.UNSUPPORTED_CONTROL_CODE,
                        (f"Unknown Pokémon Gen III extended control 0x{code:02X} at 0x{offset:X}"),
                    )
                name, argc = spec
                size = 2 + argc
                _require(data, offset, size, name)
                flush()
                output.append(_control(offset, name, data[offset : offset + size]))
                offset += size
                continue

            if value in {_KEYPAD_ICON, _EXTRA_SYMBOL}:
                _require(data, offset, 2, "two-byte symbol")
                flush()
                prefix = "KEYPAD_ICON" if value == _KEYPAD_ICON else "EXTRA_SYMBOL"
                symbol = data[offset + 1]
                output.append(
                    _control(
                        offset,
                        f"{prefix}_{symbol:02X}",
                        data[offset : offset + 2],
                    )
                )
                offset += 2
                continue

            glyph = _GLYPHS.get(value)
            if glyph is None:
                flush()
                output.append(
                    InlineToken(
                        id=f"opaque_{offset:06x}",
                        kind=TokenKind.OPAQUE,
                        movement=TokenMovement.ORDERED,
                        data_hex=f"{value:02x}",
                    )
                )
            else:
                buffer.append(glyph)
            offset += 1

        flush()
        if require_terminator:
            raise ClassicRetroError(
                ErrorCode.MISSING_TERMINATOR,
                "Pokémon Gen III text ended before EOS 0xFF",
            )
        return DecodedMessage(
            stream=TokenStream(tuple(output)),
            consumed_bytes=len(data),
            terminator_id=None,
        )

    def encode(self, stream: TokenStream, *, terminator_id: str | None = None) -> bytes:
        output = bytearray()

        for token in stream.tokens:
            if isinstance(token, TextToken):
                for character in token.text:
                    value = _BYTES_BY_GLYPH.get(character)
                    if value is None:
                        raise ClassicRetroError(
                            ErrorCode.UNENCODABLE_TEXT,
                            f"Pokémon Gen III codec has no byte for {character!r}",
                        )
                    output.append(value)
                continue

            if token.kind is TokenKind.OPAQUE:
                if token.data_hex is None:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TOKEN,
                        f"Opaque token {token.id} has no data_hex",
                    )
                output.extend(bytes.fromhex(token.data_hex))
                continue

            raw_hex = token.args.get("raw_hex")
            if isinstance(raw_hex, str):
                output.extend(bytes.fromhex(raw_hex))
                continue

            if token.kind is TokenKind.LINE_BREAK:
                output.append(_NEWLINE)
                continue

            raise ClassicRetroError(
                ErrorCode.UNENCODABLE_TOKEN,
                f"Pokémon Gen III token {token.id} is missing preserved raw bytes",
            )

        if terminator_id is not None:
            if terminator_id != "eos":
                raise ClassicRetroError(
                    ErrorCode.UNKNOWN_TERMINATOR,
                    f"Unknown Pokémon Gen III terminator: {terminator_id}",
                )
            output.append(_EOS)

        return bytes(output)


def _control(offset: int, name: str, raw: bytes) -> InlineToken:
    return InlineToken(
        id=f"control_{offset:06x}",
        kind=TokenKind.CONTROL,
        movement=TokenMovement.ORDERED,
        name=name,
        args={"raw_hex": raw.hex()},
    )


def _require(data: bytes, offset: int, size: int, label: str) -> None:
    if offset + size > len(data):
        raise ClassicRetroError(
            ErrorCode.INVALID_REBUILD_PAYLOAD,
            f"Truncated Pokémon Gen III {label} at offset 0x{offset:X}",
        )
