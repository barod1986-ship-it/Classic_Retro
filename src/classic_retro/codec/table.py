from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from classic_retro.codec.base import DecodedMessage, GameTextCodec
from classic_retro.codec.model import (
    CodecProfile,
    GlyphCode,
    InlineCode,
    TerminatorCode,
    UnknownDecodePolicy,
)
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import InlineToken, TextToken, Token, TokenKind, TokenStream


@dataclass(frozen=True, slots=True)
class _StaticCode:
    data: bytes
    value: GlyphCode | InlineCode | TerminatorCode


class TableTextCodec(GameTextCodec):
    """Safe prefix-free table codec for fixed glyph/control byte sequences."""

    def __init__(self, profile: CodecProfile) -> None:
        self.profile = profile
        self._glyphs_by_first: dict[str, tuple[GlyphCode, ...]] = {}
        for first in {glyph.sequence[0] for glyph in profile.glyphs}:
            glyphs = [glyph for glyph in profile.glyphs if glyph.sequence.startswith(first)]
            self._glyphs_by_first[first] = tuple(
                sorted(glyphs, key=lambda item: len(item.sequence), reverse=True)
            )

        self._inline_by_key = {item.semantic_key: item for item in profile.inline_codes}
        self._terminators_by_id = {item.id: item for item in profile.terminators}

        static = [
            *(_StaticCode(item.data, item) for item in profile.glyphs),
            *(_StaticCode(item.data, item) for item in profile.inline_codes),
            *(_StaticCode(item.data, item) for item in profile.terminators),
        ]
        self._static_by_first: dict[int, tuple[_StaticCode, ...]] = {}
        for first in {item.data[0] for item in static}:
            matches = [item for item in static if item.data[0] == first]
            self._static_by_first[first] = tuple(
                sorted(matches, key=lambda item: len(item.data), reverse=True)
            )

    def decode(self, data: bytes, *, require_terminator: bool = False) -> DecodedMessage:
        output: list[Token] = []
        text_buffer: list[str] = []
        offset = 0

        def flush_text() -> None:
            if text_buffer:
                output.append(TextToken("".join(text_buffer)))
                text_buffer.clear()

        while offset < len(data):
            match = self._match_static(data, offset)
            if match is None:
                if self.profile.unknown_decode is UnknownDecodePolicy.ERROR:
                    raise ClassicRetroError(
                        ErrorCode.UNKNOWN_TEXT_BYTE,
                        f"Unknown text byte 0x{data[offset]:02X} at offset 0x{offset:X}",
                    )

                flush_text()
                start = offset
                offset += 1
                while offset < len(data) and self._match_static(data, offset) is None:
                    offset += 1
                raw = data[start:offset]
                output.append(
                    InlineToken(
                        id=f"opaque_{start:06x}",
                        kind=TokenKind.OPAQUE,
                        movement=self._opaque_movement(),
                        data_hex=raw.hex(),
                    )
                )
                continue

            value = match.value
            if isinstance(value, TerminatorCode):
                flush_text()
                return DecodedMessage(
                    stream=TokenStream(tuple(output)),
                    consumed_bytes=offset + len(match.data),
                    terminator_id=value.id,
                )

            if isinstance(value, GlyphCode):
                text_buffer.append(value.sequence)
            else:
                flush_text()
                output.append(
                    InlineToken(
                        id=f"token_{offset:06x}",
                        kind=value.kind,
                        movement=value.movement,
                        name=value.name,
                        args=value.args,
                    )
                )

            offset += len(match.data)

        flush_text()
        if require_terminator:
            raise ClassicRetroError(
                ErrorCode.MISSING_TERMINATOR,
                "Text data ended before a configured terminator",
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
                output.extend(self._encode_text(token.text))
                continue

            if token.kind is TokenKind.OPAQUE:
                if token.data_hex is None:
                    raise ClassicRetroError(
                        ErrorCode.UNENCODABLE_TOKEN,
                        f"Opaque token {token.id} has no data_hex",
                    )
                output.extend(bytes.fromhex(token.data_hex))
                continue

            key = (
                token.kind,
                token.movement,
                token.name,
                tuple(sorted(token.args.items())),
            )
            code = self._inline_by_key.get(key)
            if code is None:
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TOKEN,
                    f"No codec entry matches protected token {token.id}",
                )
            output.extend(code.data)

        if terminator_id is not None:
            terminator = self._terminators_by_id.get(terminator_id)
            if terminator is None:
                raise ClassicRetroError(
                    ErrorCode.UNKNOWN_TERMINATOR,
                    f"Unknown terminator id: {terminator_id}",
                )
            output.extend(terminator.data)

        return bytes(output)

    def _encode_text(self, text: str) -> bytes:
        output = bytearray()
        index = 0

        while index < len(text):
            candidates = self._glyphs_by_first.get(text[index], ())
            glyph = next(
                (item for item in candidates if text.startswith(item.sequence, index)),
                None,
            )
            if glyph is None:
                character = text[index]
                raise ClassicRetroError(
                    ErrorCode.UNENCODABLE_TEXT,
                    (
                        f"Codec {self.profile.id} has no byte code for "
                        f"U+{ord(character):04X} {character!r}"
                    ),
                )
            output.extend(glyph.data)
            index += len(glyph.sequence)

        return bytes(output)

    def _match_static(self, data: bytes, offset: int) -> _StaticCode | None:
        if offset >= len(data):
            return None
        candidates: Iterable[_StaticCode] = self._static_by_first.get(data[offset], ())
        return next(
            (candidate for candidate in candidates if data.startswith(candidate.data, offset)),
            None,
        )

    @staticmethod
    def _opaque_movement():
        from classic_retro.text.tokens import TokenMovement

        return TokenMovement.ORDERED
