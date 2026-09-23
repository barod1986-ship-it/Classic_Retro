from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.text.tokens import TokenStream


@dataclass(frozen=True, slots=True)
class DecodedMessage:
    stream: TokenStream
    consumed_bytes: int
    terminator_id: str | None

    @property
    def terminated(self) -> bool:
        return self.terminator_id is not None


class GameTextCodec(ABC):
    @abstractmethod
    def decode(self, data: bytes, *, require_terminator: bool = False) -> DecodedMessage:
        """Decode one game-text message from the beginning of data."""

    @abstractmethod
    def encode(self, stream: TokenStream, *, terminator_id: str | None = None) -> bytes:
        """Encode one logical/visual token stream to engine bytes."""

    def verify_round_trip(
        self,
        data: bytes,
        *,
        require_terminator: bool = False,
    ) -> DecodedMessage:
        decoded = self.decode(data, require_terminator=require_terminator)
        rebuilt = self.encode(decoded.stream, terminator_id=decoded.terminator_id)
        original = data[: decoded.consumed_bytes]

        if rebuilt != original:
            mismatch = _first_mismatch(original, rebuilt)
            raise ClassicRetroError(
                ErrorCode.TEXT_CODEC_ROUNDTRIP_FAILED,
                (
                    "Text codec round-trip mismatch"
                    if mismatch is None
                    else f"Text codec round-trip mismatch at byte 0x{mismatch:X}"
                ),
            )

        return decoded


def _first_mismatch(left: bytes, right: bytes) -> int | None:
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    if len(left) != len(right):
        return limit
    return None
