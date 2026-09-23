"""Lossless game-text codecs."""

from classic_retro.codec.base import DecodedMessage, GameTextCodec
from classic_retro.codec.model import (
    CodecProfile,
    GlyphCode,
    InlineCode,
    TerminatorCode,
    UnknownDecodePolicy,
    load_codec_profile,
)
from classic_retro.codec.table import TableTextCodec

__all__ = [
    "CodecProfile",
    "DecodedMessage",
    "GameTextCodec",
    "GlyphCode",
    "InlineCode",
    "TableTextCodec",
    "TerminatorCode",
    "UnknownDecodePolicy",
    "load_codec_profile",
]
