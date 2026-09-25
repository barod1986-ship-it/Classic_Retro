from __future__ import annotations

import json

import pytest

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.engines.ff6a import CENTER, KEY_PAGE, NEWLINE, PAGE, PAUSE
from classic_retro.engines.ff6a_arabic import (
    ff6a_codes_notation,
    ff6a_notation,
    parse_ff6a_notation,
    token_codes,
)
from classic_retro.engines.golden_sun import CHARACTER_NAME, KEY_END
from classic_retro.engines.golden_sun_arabic import (
    golden_sun_codes_notation,
    golden_sun_notation,
    parse_golden_sun_notation,
)
from classic_retro.engines.pokemon_gen3_arabic import (
    parse_pokemon_gen3_notation,
    pokemon_gen3_notation,
)
from classic_retro.engines.tmc import parse_tmc_string, render_tmc_string
from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    builtin_translation_set,
    glossary_report,
    load_translation_set,
    translation_set_from_dict,
)
from classic_retro.rom.advance_wars_arabic_script import advance_wars_arabic_messages
from classic_retro.rom.ff6a_arabic_script import ff6a_arabic_messages
from classic_retro.rom.fire_emblem_arabic_script import (
    fire_emblem_arabic_legend,
    fire_emblem_arabic_messages,
)
from classic_retro.rom.fomt_arabic_script import fomt_arabic_names, fomt_arabic_strings
from classic_retro.rom.golden_sun_arabic_script import golden_sun_arabic_messages
from classic_retro.rom.metroid_fusion_arabic_script import metroid_fusion_arabic_messages
from classic_retro.rom.mlss_arabic_script import mlss_arabic_messages
from classic_retro.rom.mmbn_arabic_script import mmbn_arabic_sections
from classic_retro.rom.pmd_arabic_script import pmd_arabic_strings
from classic_retro.source.pokefirered_arabic import OAK_SPEECH_LABELS, _oak_speech_streams
from classic_retro.source.tmc_arabic import tmc_arabic_messages
from classic_retro.text.tokens import InlineToken, TextToken

TARGETS = (
    "firered",
    "minish-cap",
    "ff6a",
    "golden-sun",
    "fire-emblem",
    "pmd-red",
    "mmbn",
    "mlss",
    "fomt",
    "advance-wars",
    "metroid-fusion",
)
RLE = chr(0x202B)


def _set(*entries: Translation, glossary: tuple[GlossaryTerm, ...] = ()) -> TranslationSet:
    return TranslationSet("demo", "plain text", entries, glossary=glossary)


def _without_ids(stream) -> list:
    return [
        token.text if isinstance(token, TextToken) else (token.kind, token.name, dict(token.args))
        for token in stream.tokens
    ]


def test_every_target_ships_one_translation_per_pinned_entry():
    counts = {
        "firered": len(_oak_speech_streams()),
        "minish-cap": len(tmc_arabic_messages()),
        "ff6a": len(ff6a_arabic_messages()),
        "golden-sun": len(golden_sun_arabic_messages()),
        "fire-emblem": len(fire_emblem_arabic_messages()) + len(fire_emblem_arabic_legend()),
        "pmd-red": len(pmd_arabic_strings()),
        "mmbn": len(mmbn_arabic_sections()),
        "mlss": len(mlss_arabic_messages()),
        "fomt": len(fomt_arabic_strings()) + len(fomt_arabic_names()),
        "advance-wars": len(advance_wars_arabic_messages()),
        "metroid-fusion": len(metroid_fusion_arabic_messages()),
    }
    assert counts == {
        "firered": 13,
        "minish-cap": 26,
        "ff6a": 19,
        "golden-sun": 21,
        "fire-emblem": 12,
        "pmd-red": 158,
        "mmbn": 50,
        "mlss": 12,
        "fomt": 38,
        "advance-wars": 14,
        "metroid-fusion": 12,
    }
    for target in TARGETS:
        translations = builtin_translation_set(target)
        assert translations.target == target and not translations.is_workspace
        assert len(translations.entries) == counts[target]
        assert all(entry.source is None for entry in translations.entries)
        assert all(entry.context for entry in translations.entries)
        for term in translations.glossary:
            assert any(term.text in entry.text for entry in translations.entries), term


def test_translations_must_cover_exactly_the_pinned_entries():
    translations = _set(Translation("a", "ألف"), Translation("c", "جيم"))
    assert translations.texts(("a", "c")) == {"a": "ألف", "c": "جيم"}
    with pytest.raises(ClassicRetroError) as error:
        translations.texts(("a", "b"))
    assert error.value.code is ErrorCode.INVALID_TRANSLATION_DOCUMENT
    assert str(error.value) == "demo translations: missing b; unknown c"
    shipped = builtin_translation_set("mlss")
    shorter = TranslationSet("mlss", shipped.notation, shipped.entries[1:])
    with pytest.raises(ClassicRetroError) as error:
        mlss_arabic_messages(shorter)
    assert "missing castle_ambassador" in str(error.value)


def test_entries_are_unique_and_hold_no_direction_controls():
    with pytest.raises(ClassicRetroError) as error:
        _set(Translation("a", "ألف"), Translation("a", "باء"))
    assert error.value.code is ErrorCode.DUPLICATE_ENTRY_ID
    with pytest.raises(ClassicRetroError) as error:
        _set(Translation("a", RLE + "ألف"))
    assert error.value.code is ErrorCode.EXPLICIT_BIDI_CONTROL
    with pytest.raises(ClassicRetroError) as error:
        _set(Translation("a", "ألف", source="an original" + chr(0x200F)))
    assert error.value.code is ErrorCode.EXPLICIT_BIDI_CONTROL


def test_files_follow_the_schema(tmp_path):
    data = _set(Translation("a", "ألف", context="a line")).to_dict()
    assert translation_set_from_dict(data).texts(("a",)) == {"a": "ألف"}
    for broken in (
        {**data, "language": "en"},
        {**data, "entries": []},
        {**data, "entries": [{"id": "a", "text": "ألف", "speaker": "someone"}]},
        {key: value for key, value in data.items() if key != "notation"},
    ):
        with pytest.raises(ClassicRetroError) as error:
            translation_set_from_dict(broken)
        assert error.value.code is ErrorCode.INVALID_SCHEMA_INSTANCE
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ClassicRetroError) as error:
        load_translation_set(path, "fomt")
    assert "holds translations of demo, not fomt" in str(error.value)
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(ClassicRetroError) as error:
        load_translation_set(tmp_path / "bad.json")
    assert error.value.code is ErrorCode.INVALID_TRANSLATION_DOCUMENT
    with pytest.raises(ClassicRetroError) as error:
        builtin_translation_set("no-such-target")
    assert error.value.code is ErrorCode.INVALID_REFERENCE


def test_a_workspace_keeps_the_originals_and_says_it_is_local(tmp_path):
    translations = _set(
        Translation("a", "ألف", context="first"), Translation("b", "باء", notes="keep short")
    )
    workspace = translations.with_sources({"a": "The first invented line."}, "an invented image")
    path = tmp_path / "demo.workspace.json"
    path.write_text(workspace.dumps(), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["workspace"]["from"] == "an invented image"
    assert "Do not commit" in data["workspace"]["notice"]
    assert data["entries"][0] == {
        "id": "a",
        "context": "first",
        "source": "The first invented line.",
        "text": "ألف",
    }
    assert "source" not in data["entries"][1] and data["entries"][1]["notes"] == "keep short"
    loaded = load_translation_set(path, "demo")
    assert loaded == workspace and loaded.is_workspace
    assert "workspace" not in translations.to_dict()


def test_the_glossary_report_uses_the_longest_term():
    glossary = (
        GlossaryTerm("Nova", "نوفا"),
        GlossaryTerm("Nova.EXE", "Nova.EXE"),
        GlossaryTerm("Stone", "الحجر"),
    )
    workspace = _set(
        Translation("a", "برنامج Nova.EXE", source="Run Nova.EXE now."),
        Translation("b", "هيا!", source="Nova, come here. Nova!"),
        Translation("c", "الحجر هنا", source="The Stone is here; Stones and Novas too."),
        Translation("d", "لا شيء", source="Milestone, Supernova."),
        Translation("e", "ما زال ينتظر"),
        glossary=glossary,
    )
    assert glossary_report(workspace) == [{"id": "b", "term": "Nova", "expected": "نوفا"}]


def test_golden_sun_notation_rebuilds_every_shipped_message():
    for message in golden_sun_arabic_messages():
        text = golden_sun_notation(message.stream)
        assert parse_golden_sun_notation(text, f"m{message.index}_") == message.stream
    stream = parse_golden_sun_notation("مرحبا {CHARACTER_NAME 01}!\nهيا{+KEY_PAGE}{KEY_END}", "t")
    assert golden_sun_notation(stream) == "مرحبا {CHARACTER_NAME 01}!\nهيا{+KEY_PAGE}{KEY_END}"
    for broken in ("{CHARACTER_NAME}", "{NO_SUCH_COMMAND}", "{KEY_END 01}", "text } more", "{}"):
        with pytest.raises(ClassicRetroError) as error:
            parse_golden_sun_notation(broken, "t")
        assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    codes = [CHARACTER_NAME, 0x01, *b", wake up", 0x03, *b"{x}", 0x85, KEY_END]
    assert golden_sun_codes_notation(codes) == (
        "{CHARACTER_NAME 01}, wake up\n{7B}x{7D}{85}{KEY_END}"
    )


def test_ff6a_notation_rebuilds_every_shipped_message():
    for message in ff6a_arabic_messages():
        text = ff6a_notation(message.stream)
        assert parse_ff6a_notation(text, f"m{message.index}_") == message.stream
    stream = parse_ff6a_notation("{CENTER}أ\nب{PAUSE 14C}{PAGE}ج{+PAUSE 154 PAGE}د{+KEY_PAGE}", "t")
    commands = [token_codes(token) for token in stream.inline_tokens]
    assert commands == [
        (CENTER,),
        (NEWLINE,),
        (PAUSE, 0x14C),
        (PAGE, NEWLINE),
        (PAUSE, 0x154, PAGE, NEWLINE),
        (KEY_PAGE,),
    ]
    assert [token.args.get("inserted", False) for token in stream.inline_tokens] == [
        False,
        False,
        False,
        False,
        True,
        True,
    ]
    for broken in ("{PAUSE}", "{NO_SUCH_COMMAND}", "a { b", "{}"):
        with pytest.raises(ClassicRetroError) as error:
            parse_ff6a_notation(broken, "t")
        assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE
    characters = {1: "e", 2: "t", 3: "{"}
    codes = [CENTER, 2, 1, 0x50, NEWLINE, 3, PAUSE, 0x14C, PAGE, NEWLINE, 0x10F]
    assert ff6a_codes_notation(codes, characters) == (
        "{CENTER}te{050}\n{003}{PAUSE 14C}{PAGE}{END}"
    )


def test_firered_notation_rebuilds_every_shipped_message():
    streams = _oak_speech_streams()
    assert tuple(streams) == OAK_SPEECH_LABELS
    for stream in streams.values():
        text = pokemon_gen3_notation(stream)
        assert _without_ids(parse_pokemon_gen3_notation(text, "x")) == _without_ids(stream)
    stream = parse_pokemon_gen3_notation("أهلا {PLAYER}!\nمعك {RIVAL}\\p", "t")
    assert pokemon_gen3_notation(stream) == "أهلا {PLAYER}!\nمعك {RIVAL}\\p"
    assert [token.name for token in stream.inline_tokens] == [
        "PLAYER",
        None,
        "RIVAL",
        "PROMPT_CLEAR",
    ]
    for broken in ("{NAME}", "\\l", "a } b"):
        with pytest.raises(ClassicRetroError) as error:
            parse_pokemon_gen3_notation(broken, "t")
        assert error.value.code is ErrorCode.UNSUPPORTED_CONTROL_CODE


def test_minish_cap_notation_reads_arabic_translations():
    for message in tmc_arabic_messages():
        text = render_tmc_string(message.stream, glyph_text=False)
        back = parse_tmc_string(text, id_prefix="x", glyph_text=False)
        assert _without_ids(back) == _without_ids(message.stream)
    with pytest.raises(ClassicRetroError) as error:
        parse_tmc_string("مرحبا")
    assert error.value.code is ErrorCode.UNENCODABLE_TEXT
    stream = parse_tmc_string("{Color:Green}مرحبا{Color:White}\n{Player}", glyph_text=False)
    assert [token.name for token in stream.inline_tokens if isinstance(token, InlineToken)] == [
        "COLOR",
        "COLOR",
        None,
        "PLAYER",
    ]
