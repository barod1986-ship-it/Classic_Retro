from __future__ import annotations

import zlib
from collections.abc import Mapping
from typing import Any

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.transform.base import DecodedTransform, ResourceTransform

_DEFAULT_MAX_OUTPUT = 64 * 1024 * 1024


class IdentityTransform(ResourceTransform):
    id = "identity"

    def decode(self, data: bytes) -> DecodedTransform:
        return DecodedTransform(data)

    def encode(self, payload: bytes, metadata: Mapping[str, Any]) -> bytes:
        return payload


class DeflateTransform(ResourceTransform):
    def __init__(
        self,
        transform_id: str,
        *,
        wbits: int,
        level: int = 9,
        max_output_bytes: int = _DEFAULT_MAX_OUTPUT,
    ) -> None:
        if level < -1 or level > 9:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSFORM_PROFILE,
                "Deflate level must be -1 or 0..9",
            )
        if max_output_bytes < 1:
            raise ClassicRetroError(
                ErrorCode.INVALID_TRANSFORM_PROFILE,
                "max_output_bytes must be positive",
            )
        self.id = transform_id
        self.wbits = wbits
        self.level = level
        self.max_output_bytes = max_output_bytes

    def decode(self, data: bytes) -> DecodedTransform:
        try:
            payload = _decompress_exact(
                data,
                wbits=self.wbits,
                max_output_bytes=self.max_output_bytes,
            )
        except zlib.error as exc:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_DECODE_FAILED,
                f"{self.id} decompression failed: {exc}",
            ) from exc
        return DecodedTransform(payload)

    def encode(self, payload: bytes, metadata: Mapping[str, Any]) -> bytes:
        try:
            return zlib.compress(payload, level=self.level, wbits=self.wbits)
        except zlib.error as exc:
            raise ClassicRetroError(
                ErrorCode.TRANSFORM_ENCODE_FAILED,
                f"{self.id} compression failed: {exc}",
            ) from exc


def build_identity(options: Mapping[str, Any]) -> ResourceTransform:
    if options:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            "identity transform does not accept options",
        )
    return IdentityTransform()


def build_zlib(options: Mapping[str, Any]) -> ResourceTransform:
    _reject_unknown_options(options, {"wbits", "level", "max_output_bytes"})
    wbits = _integer_option(options, "wbits", 15)
    if not 9 <= wbits <= 15:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            "zlib wbits must be between 9 and 15",
        )
    return DeflateTransform(
        "zlib",
        wbits=wbits,
        level=_integer_option(options, "level", 9),
        max_output_bytes=_integer_option(options, "max_output_bytes", _DEFAULT_MAX_OUTPUT),
    )


def build_raw_deflate(options: Mapping[str, Any]) -> ResourceTransform:
    _reject_unknown_options(options, {"window_bits", "level", "max_output_bytes"})
    window_bits = _integer_option(options, "window_bits", 15)
    if not 9 <= window_bits <= 15:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            "raw-deflate window_bits must be between 9 and 15",
        )
    return DeflateTransform(
        "raw-deflate",
        wbits=-window_bits,
        level=_integer_option(options, "level", 9),
        max_output_bytes=_integer_option(options, "max_output_bytes", _DEFAULT_MAX_OUTPUT),
    )


def build_gzip(options: Mapping[str, Any]) -> ResourceTransform:
    _reject_unknown_options(options, {"level", "max_output_bytes"})
    return DeflateTransform(
        "gzip",
        wbits=31,
        level=_integer_option(options, "level", 9),
        max_output_bytes=_integer_option(options, "max_output_bytes", _DEFAULT_MAX_OUTPUT),
    )


def _decompress_exact(data: bytes, *, wbits: int, max_output_bytes: int) -> bytes:
    decompressor = zlib.decompressobj(wbits)
    payload = decompressor.decompress(data, max_output_bytes + 1)

    if len(payload) > max_output_bytes or decompressor.unconsumed_tail:
        raise ClassicRetroError(
            ErrorCode.TRANSFORM_OUTPUT_LIMIT,
            f"Decoded resource exceeds {max_output_bytes} bytes",
        )

    remaining = max_output_bytes + 1 - len(payload)
    payload += decompressor.flush(remaining)

    if len(payload) > max_output_bytes:
        raise ClassicRetroError(
            ErrorCode.TRANSFORM_OUTPUT_LIMIT,
            f"Decoded resource exceeds {max_output_bytes} bytes",
        )
    if not decompressor.eof:
        raise ClassicRetroError(
            ErrorCode.TRANSFORM_DECODE_FAILED,
            "Compressed resource ended before the stream was complete",
        )
    if decompressor.unused_data:
        raise ClassicRetroError(
            ErrorCode.TRANSFORM_DECODE_FAILED,
            "Compressed resource contains trailing data outside the stream",
        )

    return payload


def _integer_option(options: Mapping[str, Any], name: str, default: int) -> int:
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            f"Transform option {name} must be an integer",
        )
    return value


def _reject_unknown_options(options: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ClassicRetroError(
            ErrorCode.INVALID_TRANSFORM_PROFILE,
            "Unknown transform option(s): " + ", ".join(unknown),
        )
