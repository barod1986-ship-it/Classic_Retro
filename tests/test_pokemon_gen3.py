from __future__ import annotations

from pathlib import Path

from classic_retro.adapters.discovery import detect_game
from classic_retro.adapters.registry import build_registry
from classic_retro.core.identity import FileFingerprint
from classic_retro.engines.pokemon_gen3 import PokemonGen3TextCodec
from classic_retro.media.model import MediaKind, MediaMember, MediaSet
from classic_retro.text.tokens import TokenKind


def test_firered_rev1_exact_revision_is_supported():
    fingerprint = FileFingerprint(
        name="firered_rev1.gba",
        size=16_777_216,
        sha256="729041b940afe031302d630fdbe57c0c145f3f7b6d9b8eca5e98678d0ca4d059",
    )
    media = MediaSet(
        entry_path=Path("firered_rev1.gba"),
        kind=MediaKind.SINGLE_FILE,
        members=(
            MediaMember(
                role="primary",
                path=Path("firered_rev1.gba"),
                fingerprint=fingerprint,
            ),
        ),
    )

    match = detect_game(media, "gba", build_registry(load_external=False))

    assert match is not None
    assert match.id == "pokemon-firered-rev1-en"
    assert match.engine_id == "gba.pokemon-gen3"
    assert match.source_build is not None
    assert match.source_build.build_target == "firered_rev1"


def test_pokemon_gen3_codec_round_trip_with_placeholder_and_control():
    codec = PokemonGen3TextCodec()
    data = bytes.fromhex("c2 dd ab fd 01 fc 08 1e fe bb ff")

    decoded = codec.verify_round_trip(data, require_terminator=True)

    assert decoded.stream.visible_text == "Hi!A"
    assert decoded.terminator_id == "eos"
    assert [token.kind for token in decoded.stream.inline_tokens] == [
        TokenKind.VARIABLE,
        TokenKind.CONTROL,
        TokenKind.LINE_BREAK,
    ]


def test_unknown_single_byte_is_preserved_as_opaque():
    codec = PokemonGen3TextCodec()
    data = bytes.fromhex("18 ff")

    decoded = codec.verify_round_trip(data, require_terminator=True)

    assert decoded.stream.inline_tokens[0].kind is TokenKind.OPAQUE
    assert decoded.stream.inline_tokens[0].data_hex == "18"
