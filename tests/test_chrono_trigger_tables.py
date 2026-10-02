"""Adding a string table to the Chrono Trigger translation, on a synthetic ROM."""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError
from classic_retro.engines import chrono_trigger as engine
from classic_retro.engines.chrono_trigger_arabic import (
    CELL,
    CLEAR,
    INK,
    SPACE_WIDTH,
    WIDEST,
    CtFont,
    CtGlyph,
)
from classic_retro.rom import chrono_trigger_arabic_script as script
from classic_retro.rom import chrono_trigger_tables as tables
from classic_retro.rom.chrono_trigger_arabic import ROM_BANK, ROM_SIZE

TABLE = 0x384650  # $F8:4650, one of the dialogue's tables
EVENTS = 0x3D0000


def _text(text: str) -> bytes:
    """Invented English in the game's codes; | is a line end, ^ a {pause 00}."""
    data = bytearray()
    for character in text:
        if character == "|":
            data.append(engine.LINE)
        elif character == "^":
            data += bytes((engine.PAUSE, 0x00))
        else:
            data.append(engine.FIRST_CHARACTER + engine.CHARACTERS.index(character))
    return bytes(data)


def _block(data: bytes) -> bytes:
    """``data`` as a compressed block of copied bytes only (a control byte of zero
    copies eight)."""
    data = data + bytes(-len(data) % 8)
    body = b"".join(b"\x00" + data[at : at + 8] for at in range(0, len(data), 8))
    return struct.pack("<H", len(body)) + body + b"\x00"


def _rom() -> bytearray:
    """A table of five strings: 0 has a {pause 00} that 1 runs on from; 2 asks a
    question an event opens a decision box on; 3 ends with options no event asks."""
    rom = bytearray(ROM_SIZE)
    strings = [
        _text("Hi^Yo") + b"\x00",
        None,  # the tail of 0
        _text("Go?|   Yes|   No") + b"\x00",
        _text("Pick|   Red|   Blue") + b"\x00",
        _text("Bye") + b"\x00",
    ]
    at = TABLE + 2 * len(strings)
    pointers = []
    for data in strings:
        if data is None:
            pointers.append(pointers[0] + len(_text("Hi^")))
            continue
        pointers.append(at & 0xFFFF)
        rom[at : at + len(data)] = data
        at += len(data)
    struct.pack_into(f"<{len(pointers)}H", rom, TABLE, *pointers)
    # One location: its script names the table and opens a decision on string 2,
    # its choices on lines 2 and 3 (1 and 2 from zero).
    address = ROM_BANK + TABLE
    event = bytes((tables.SET_STRING_TABLE, address & 0xFF, address >> 8 & 0xFF, address >> 16))
    event += bytes((0xC0, 2, 1 << 2 | 2))
    block = _block(event)
    rom[EVENTS : EVENTS + len(block)] = block
    pointer = ROM_BANK + EVENTS
    rom[tables.LOCATION_EVENTS : tables.LOCATION_EVENTS + 3] = pointer.to_bytes(3, "little")
    return rom


def test_a_block_copies_bytes_and_earlier_output():
    rom = bytearray(64)
    # One control byte: a byte, a copy of three from one back, then six bytes.
    body = bytes((0x02,)) + b"A" + bytes((0x01, 0x00)) + b"BCDEFG"
    rom[0:2] = struct.pack("<H", len(body))
    rom[2 : 2 + len(body)] = body
    assert tables.decompress(bytes(rom), 0) == b"AAAABCDEFG"
    assert tables.decompress(bytes(_block(b"0123456789")), 0) == b"0123456789" + bytes(6)


def test_the_plan_pins_every_message_with_its_decisions_and_tails():
    rom = bytes(_rom())
    plan, originals = tables.plan_table(
        rom, TABLE, "test", "Invented, places", verify_identity=False
    )

    assert plan["table"] == {
        "key": "test",
        "address": "$F8:4650",
        "count": 5,
        "what": "Invented, places",
    }
    assert list(plan["messages"]) == [f"test.{n:03d}" for n in range(5)]
    data = engine.string_bytes(rom, engine.table_string(rom, TABLE, 0))
    assert plan["messages"]["test.000"]["skeleton"] == ["{pause 00}"]
    assert plan["messages"]["test.000"]["sha256"] == __import__("hashlib").sha256(data).hexdigest()
    assert plan["tails"] == {"test.001": {"of": "test.000", "segment": 1}}
    assert plan["decisions"] == {"test.002": [1, 2]}
    assert [(item["id"], item["option_lines"]) for item in plan["review"]] == [("test.003", [1, 2])]
    assert plan["events"] == {"read": 1, "unread": 0}
    assert originals["test.002"] == "Go?{line}   Yes{line}   No"
    # The plan holds no text of the game: pins, commands and numbers.
    assert "Yes" not in json.dumps(plan) and "Bye" not in json.dumps(plan)

    workspace = tables.table_workspace(plan, originals)
    assert workspace.is_workspace and [e.text for e in workspace.entries] == [""] * 5
    assert "decision box" in workspace.entries[2].notes
    assert "test.000" in workspace.entries[1].notes


def test_a_translated_table_is_not_planned_again():
    with pytest.raises(ClassicRetroError, match="translated already"):
        tables.plan_table(
            bytes(_rom()), script.TABLES["guardia"].address, "x", verify_identity=False
        )
    with pytest.raises(ClassicRetroError, match="lower-case"):
        tables.plan_table(bytes(_rom()), TABLE, "Bad Key", verify_identity=False)
    with pytest.raises(ClassicRetroError, match="not one of the dialogue's tables"):
        tables.table_offset("$C0:0000")
    assert tables.table_offset("$F8:4650") == tables.table_offset("0x384650") == TABLE


def _fake_font(font_path=None, glyph_map=None, used=(), **_kwargs) -> CtFont:
    """Every glyph a bar 6 pixels wide; the space the real one."""
    bar = CtGlyph(6, tuple((INK,) * 6 + (CLEAR,) * (WIDEST - 6) for _ in range(CELL)))
    space = CtGlyph(SPACE_WIDTH, ((CLEAR,) * WIDEST,) * CELL)
    return CtFont({glyph_map.code(c): space if c == " " else bar for c in used}, 9)


@pytest.fixture
def planned(monkeypatch, tmp_path):
    monkeypatch.setattr(tables, "build_chrono_trigger_font", _fake_font)
    plan, originals = tables.plan_table(
        bytes(_rom()), TABLE, "test", "Invented, places", verify_identity=False
    )
    return plan, tables.table_workspace(plan, originals), tmp_path / "font.ttf"


GOOD = {
    "test.000": "أهلا{pause 00}يا",
    "test.001": "يا",
    "test.002": "نذهب؟{line}{choice}نعم{line}{choice}لا",
    "test.003": "اختر{line}أحمر{line}أزرق",
    "test.004": "وداعا",
}


def test_check_table_checks_each_translated_message_as_the_build_does(planned):
    plan, workspace, font = planned
    assert tables.check_table(plan, workspace, font) | {"warnings": []} == {
        "table": "test",
        "messages": 5,
        "checked": 0,
        "untranslated": 5,
        "ok": True,
        "errors": [],
        "warnings": [],
        "checked_with_font": True,
    }
    good = tables.check_table(plan, tables.with_text(workspace, GOOD), font)
    assert good["ok"] and good["checked"] == 5 and good["untranslated"] == 0

    bad = tables.with_text(
        workspace,
        {
            "test.000": "أهلا يا",  # the {pause 00} dropped
            "test.002": "نذهب؟{line}نعم{line}لا",  # no choices where the event asks them
            "test.003": "اختر{line}{choice}أحمر{line}{choice}أزرق",  # choices no event asks
            "test.004": "Bye",
        },
    )
    report = tables.check_table(plan, bad, font)
    assert [(e["id"], e["code"]) for e in report["errors"]] == [
        ("test.000", "TOKEN_ORDER_VIOLATION"),
        ("test.002", "INVALID_TRANSLATION_DOCUMENT"),
        ("test.003", "INVALID_TRANSLATION_DOCUMENT"),
        ("test.004", "UNENCODABLE_TEXT"),
    ]
    # A tail that is not its head's Arabic from the segment on.
    tail = tables.check_table(plan, tables.with_text(workspace, {**GOOD, "test.001": "هنا"}), font)
    assert [e["id"] for e in tail["errors"]] == ["test.001"]


def test_adopt_table_pins_the_table_and_ships_its_arabic_without_the_originals(planned, tmp_path):
    plan, workspace, font = planned
    script_copy = tmp_path / "script.py"
    shutil.copy(tables.SCRIPT_PATH, script_copy)
    shipped = Path(tables.SCRIPT_PATH).parents[1] / "translations" / "chrono-trigger.json"
    shipped_copy = tmp_path / "chrono-trigger.json"
    shutil.copy(shipped, shipped_copy)

    with pytest.raises(ClassicRetroError, match="not ready"):
        tables.adopt_table(
            plan, workspace, font, script_path=script_copy, translations_path=shipped_copy
        )
    with pytest.raises(ClassicRetroError, match="--what"):
        tables.adopt_table(
            plan,
            workspace,
            font,
            what="Here: there",
            script_path=script_copy,
            translations_path=shipped_copy,
        )
    report = tables.adopt_table(
        plan,
        tables.with_text(workspace, GOOD),
        font,
        script_path=script_copy,
        translations_path=shipped_copy,
    )
    assert report["messages"] == 5 and report["decisions"] == 1

    source = script_copy.read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    exec(compile(source, str(script_copy), "exec"), namespace)
    assert namespace["TABLES"]["test"].address == TABLE and namespace["TABLES"]["test"].count == 5
    assert namespace["DECISIONS"]["test.002"] == (1, 2)
    pins = namespace["_SOURCES"]
    assert pins["test.000"] == (0, plan["messages"]["test.000"]["sha256"], ("{pause 00}",))
    assert len(pins) == len(script._SOURCES) + 5

    data = json.loads(shipped_copy.read_text(encoding="utf-8"))
    added = {entry["id"]: entry for entry in data["entries"] if entry["id"].startswith("test.")}
    assert added["test.002"] == {
        "id": "test.002",
        "context": "Message 2 of the test table (Invented...)",
        "text": GOOD["test.002"],
    }
    # The shipped file holds the Arabic and where each message is, never an original.
    assert not any(word in json.dumps(added) for word in ("Hi", "Yo", "Go?", "Yes", "Pick", "Bye"))
    with pytest.raises(ClassicRetroError, match="in TABLES already"):
        tables.adopt_table(
            plan,
            tables.with_text(workspace, GOOD),
            font,
            script_path=script_copy,
            translations_path=shipped_copy,
        )


def test_the_commands_write_local_files_and_check_them(planned, tmp_path, capsys, monkeypatch):
    rom_path = tmp_path / "game.sfc"
    rom_path.write_bytes(bytes(_rom()))
    monkeypatch.setattr(tables, "verify_usa_image", lambda rom: None)
    monkeypatch.setattr(
        "classic_retro.localization.builtin.chrono_trigger.chrono_trigger_arabic.verify_usa_image",
        lambda rom: None,
    )
    assert main(["chrono-trigger", "tables", str(rom_path)]) == 0
    listed = {row["address"]: row for row in json.loads(capsys.readouterr().out)}
    assert listed["$F8:4650"] == {"address": "$F8:4650", "strings": 5, "translated": None}

    out = tmp_path / "out"
    argv = ["chrono-trigger", "new-table", str(rom_path), "$F8:4650", "test", "--out-dir", str(out)]
    assert main(argv) == 0
    made = json.loads(capsys.readouterr().out)
    assert made["decisions"] == 1 and made["tails"] == 1 and made["review"] == 1
    assert main(argv) == 2 and "OUTPUT_EXISTS" in capsys.readouterr().err

    workspace = json.loads((out / "test.workspace.json").read_text(encoding="utf-8"))
    for entry in workspace["entries"]:
        entry["text"] = GOOD[entry["id"]]
    (out / "test.workspace.json").write_text(
        json.dumps(workspace, ensure_ascii=False), encoding="utf-8"
    )
    check = [
        "chrono-trigger",
        "check-table",
        str(out / "test.plan.json"),
        str(out / "test.workspace.json"),
    ]
    assert main(check) == 0
    assert json.loads(capsys.readouterr().out)["checked"] == 5
