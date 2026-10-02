"""``targets check-entries``: every refused entry and its reason, for any target."""

from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.localization.entries import (
    entry_report,
    load_batch,
    locate_failures,
    notation_warnings,
    tolerated_tokens,
)
from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    builtin_translation_set,
)

# An invented target's rules: "!" is refused in any entry ("%" crashes it), a line
# is at most 12 characters wide with a font, the whole script holds at most two
# "ق", and the greeting may be six characters longer than the name.
BUDGET = 2


def _check(font, preview_dir, translations):
    assert preview_dir is None
    texts = {entry.id: entry.text for entry in translations.entries}
    for text in texts.values():
        if "!" in text:
            raise ClassicRetroError(ErrorCode.UNENCODABLE_TEXT, "no glyph for '!'")
        if "%" in text:
            raise ValueError("the encoder fell over")
        if font is not None and len(text) > 12:
            raise ClassicRetroError(ErrorCode.TEXT_BOX_OVERFLOW, f"{len(text)} > 12")
    if sum(text.count("ق") for text in texts.values()) > BUDGET:
        raise ClassicRetroError(ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED, "too many ق")
    # A message must not be longer than the name it carries allows.
    if len(texts["greeting"]) > 6 + len(texts["name"]):
        raise ClassicRetroError(ErrorCode.TEXT_OVERFLOW, "the greeting outgrows the name")
    return {}


def _baseline(count: int = 8) -> TranslationSet:
    entries = [Translation("name", "سامي"), Translation("greeting", "أهلا")]
    entries += [Translation(f"line.{n}", "نص") for n in range(count)]
    return TranslationSet("demo", "plain text", tuple(entries))


def _locate(baseline: TranslationSet, changes: dict[str, str], font=None, max_runs=500):
    texts = {entry.id: entry.text for entry in baseline.entries} | changes
    return locate_failures(_check, baseline, texts, list(changes), font, max_runs=max_runs)


def _with(baseline: TranslationSet, entry_id: str, text: str) -> TranslationSet:
    return replace(
        baseline,
        entries=tuple(replace(e, text=text) if e.id == entry_id else e for e in baseline.entries),
    )


def test_every_failing_entry_is_found_with_its_own_error():
    located = _locate(_baseline(), {"line.1": "نص!", "line.5": "سطر", "line.6": "%"})

    assert [(e["id"], e["code"], e["font"]) for e in located.errors] == [
        ("line.1", "UNENCODABLE_TEXT", False),
        ("line.6", "INTERNAL_ERROR", False),
    ]
    assert located.errors[1]["message"] == "ValueError: the encoder fell over"
    assert located.groups == () and located.undecided == ()
    assert located.baseline_error is None


def test_nothing_changed_runs_nothing_and_a_passing_set_runs_once():
    assert _locate(_baseline(), {}).runs == 0
    located = _locate(_baseline(), {"line.0": "سطر", "line.1": "كلام"})
    assert located.errors == () and located.runs == 1


def test_the_font_phase_finds_what_only_the_layout_refuses():
    located = _locate(
        _baseline(), {"line.0": "نص طويل جدا جدا", "line.1": "!", "line.2": "قصير"}, font="f"
    )

    assert [(e["id"], e["code"], e["font"]) for e in located.errors] == [
        ("line.0", "TEXT_BOX_OVERFLOW", True),
        ("line.1", "UNENCODABLE_TEXT", False),
    ]


def test_an_entry_refused_only_with_others_names_the_fewest_of_them():
    located = _locate(_baseline(), {f"line.{n}": "ق" for n in range(5)})

    # line.0 and line.1 fill the budget of two; each later one overflows it with them.
    assert located.errors == ()
    assert [(g["id"], g["with"], g["code"]) for g in located.groups] == [
        ("line.2", ["line.0", "line.1"], "ARABIC_GLYPH_CAPACITY_EXCEEDED"),
        ("line.3", ["line.0", "line.1"], "ARABIC_GLYPH_CAPACITY_EXCEEDED"),
        ("line.4", ["line.0", "line.1"], "ARABIC_GLYPH_CAPACITY_EXCEEDED"),
    ]


def test_an_entry_that_passes_with_the_other_changes_is_not_an_error():
    # The greeting grows with a longer name: refused against the baseline's name,
    # and not with the translator's.
    changes = {"greeting": "أهلا أهلا أهلا", "name": "سامي سالم", "line.0": "!"}
    located = _locate(_baseline(), changes)

    assert [e["id"] for e in located.errors] == ["line.0"] and located.groups == ()
    # Alone, the same changes pass: nothing is searched.
    del changes["line.0"]
    assert _locate(_baseline(), changes).runs == 1


def test_changes_are_judged_together_so_a_freed_budget_is_not_spent_twice():
    # The baseline's line.7 holds two ق; the batch frees it and gives three
    # entries one each: two fit, the third is refused with the others in place.
    baseline = _with(_baseline(), "line.7", "قق")
    located = _locate(baseline, {"line.3": "ق", "line.4": "ق", "line.5": "ق", "line.7": "نص"})

    assert [(e["id"], e["code"]) for e in located.errors] == [
        ("line.4", "ARABIC_GLYPH_CAPACITY_EXCEEDED")
    ]
    assert located.groups == ()


def test_a_budget_the_other_changes_free_is_no_error():
    baseline = _with(_baseline(), "line.7", "ق")
    changes = {f"line.{n}": "سطر" for n in (0, 3, 4, 6)}
    changes |= {"line.1": "ق", "line.2": "ق", "line.5": "!", "line.7": "نص"}
    located = _locate(baseline, changes)

    assert [e["id"] for e in located.errors] == ["line.5"] and located.groups == ()


def test_an_entry_that_passes_without_the_font_is_laid_out_with_its_partners():
    # With the longer name the greeting passes the name rule, but not the font's 12.
    changes = {"name": "سامي سالم", "greeting": "أهلا أهلا أهلا", "line.0": "!"}
    located = _locate(_baseline(), changes, font="f")

    assert [(e["id"], e["code"], e["font"]) for e in located.errors] == [
        ("greeting", "TEXT_BOX_OVERFLOW", True),
        ("line.0", "UNENCODABLE_TEXT", False),
    ]


def test_a_baseline_that_fails_is_said_and_blames_no_entry():
    located = _locate(_with(_baseline(), "line.7", "خطأ!"), {"line.0": "!"})

    assert located.baseline_error == {
        "code": "UNENCODABLE_TEXT",
        "message": "no glyph for '!'",
        "font": False,
    }
    assert located.errors == () and located.undecided == ()


def test_a_baseline_refused_only_with_the_font_keeps_the_errors_found_without_it():
    located = _locate(
        _with(_baseline(), "line.7", "نص طويل جدا جدا"), {"line.0": "!", "line.1": "سطر"}, font="f"
    )

    assert [e["id"] for e in located.errors] == ["line.0"]
    assert located.baseline_error == {
        "code": "TEXT_BOX_OVERFLOW",
        "message": "15 > 12",
        "font": True,
    }


def test_the_run_limit_leaves_entries_undecided_and_says_so():
    changes = {f"line.{n}": "!" if n == 2 else "سطر" for n in range(8)}
    complete = _locate(_baseline(), changes)
    assert [e["id"] for e in complete.errors] == ["line.2"] and complete.undecided == ()

    stopped = _locate(_baseline(), changes, max_runs=3)
    assert stopped.runs == 3 and stopped.errors == ()
    assert "line.2" in stopped.undecided
    # What is decided is never undecided too.
    for limit in range(1, complete.runs):
        located = _locate(_baseline(), changes, max_runs=limit)
        decided = {e["id"] for e in located.errors}
        assert decided.isdisjoint(located.undecided) and located.undecided


def _write(tmp_path, entries, *, target="demo", glossary=()) -> object:
    path = tmp_path / "batch.json"
    data = {
        "schema_version": "1.0",
        "target": target,
        "language": "ar",
        "notation": "plain text",
        "entries": entries,
    }
    if glossary:
        data["glossary"] = glossary
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_batch_takes_every_entry_it_lacks_from_the_baseline(tmp_path):
    path = _write(
        tmp_path,
        [
            {"id": "line.3", "text": "سطر", "source": "A line"},
            {"id": "ghost", "text": "شبح"},
            {"id": "line.3", "text": "سطر آخر"},
            {"id": "line.4", "text": "نص‫"},
            {"id": "line.5", "text": "كلام"},
        ],
    )
    batch = load_batch(path, "demo", _baseline())

    texts = {entry.id: entry.text for entry in batch.translations.entries}
    assert texts["line.3"] == "سطر" and texts["line.4"] == "نص" and texts["line.0"] == "نص"
    assert batch.ids == ("line.3", "line.4", "line.5")
    assert batch.sources == {"line.3": "A line"}
    assert [(p["id"], p["code"]) for p in batch.problems] == [
        ("ghost", "INVALID_TRANSLATION_DOCUMENT"),
        ("line.3", "DUPLICATE_ENTRY_ID"),
        ("line.4", "EXPLICIT_BIDI_CONTROL"),
    ]

    narrowed = load_batch(path, "demo", _baseline(), ["line.[45]"])
    assert narrowed.ids == ("line.4", "line.5") and narrowed.problems[0]["id"] == "line.4"
    with pytest.raises(ClassicRetroError, match="matches typo"):
        load_batch(path, "demo", _baseline(), ["typo.*"])


def test_an_id_given_twice_is_checked_with_its_first_text(tmp_path):
    path = _write(tmp_path, [{"id": "line.3", "text": "Hi!"}, {"id": "line.3", "text": "سطر"}])
    report = entry_report(_check, load_batch(path, "demo", _baseline()), None, max_runs=10)

    assert [(e["id"], e["code"]) for e in report["errors"]] == [
        ("line.3", "DUPLICATE_ENTRY_ID"),
        ("line.3", "UNENCODABLE_TEXT"),
    ]
    assert [w["kind"] for w in report["warnings"]] == ["latin_letters"]


def test_a_batch_of_another_target_or_not_json_is_refused(tmp_path):
    with pytest.raises(ClassicRetroError, match="not demo"):
        load_batch(
            _write(tmp_path, [{"id": "a", "text": "ب"}], target="other"), "demo", _baseline()
        )
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ClassicRetroError, match="Could not read"):
        load_batch(bad, "demo", _baseline())


def test_the_report_puts_errors_groups_and_warnings_in_the_baselines_order(tmp_path):
    path = _write(
        tmp_path,
        [
            {"id": "line.6", "text": "قق", "source": "Kick off 3 games"},
            {"id": "line.5", "text": "قق", "source": "Kick"},
            {"id": "line.2", "text": "Go!", "source": "Go Mila!"},
            {"id": "ghost", "text": "شبح"},
        ],
        glossary=[{"term": "Mila", "text": "ميلا"}],
    )
    report = entry_report(_check, load_batch(path, "demo", _baseline()), None, max_runs=100)

    assert report["ok"] is False
    assert (report["entries"], report["from_baseline"], report["changed"]) == (3, 7, 3)
    assert [(e["id"], e["code"]) for e in report["errors"]] == [
        ("ghost", "INVALID_TRANSLATION_DOCUMENT"),
        ("line.2", "UNENCODABLE_TEXT"),
    ]
    assert [(g["id"], g["with"]) for g in report["group_errors"]] == [("line.6", ["line.5"])]
    assert [(w["id"], w["kind"]) for w in report["warnings"]] == [
        ("line.2", "latin_letters"),
        ("line.2", "no_arabic"),
        ("line.2", "glossary"),
        ("line.6", "numbers_missing"),
    ]


def test_notation_warnings_read_only_the_notation():
    def kinds(text, source=None, tolerated=frozenset()):
        return {w["kind"]: w["detail"] for w in notation_warnings("e", text, source, tolerated)}

    assert kinds("مرحبا {Crono} [X] \\p") == {}
    assert kinds("مرحبا Bob") == {"latin_letters": "Latin letters outside the commands: Bob"}
    assert set(kinds("مَرحبا ﻣ")) == {"vowel_marks", "presentation_forms"}
    assert kinds("نص {wait") == {
        "latin_letters": "Latin letters outside the commands: wait",
        "unbalanced_brackets": "1 '{' against 0 '}'",
    }
    assert set(kinds(" ")) == {"empty"}
    assert set(kinds("Hello", "Hello")) == {"untranslated", "latin_letters"}
    assert kinds("{wait}مرحبا{wait}{x}", "Hi{wait}{y}") == {
        "commands_differ": "dropped {y}; added {wait} {x}"
    }
    assert kinds("مرحبا{line}{x}", "Hi{x}", tolerated_tokens([("A{line}", "ب")])) == {}
    assert kinds("خذ ١٠ وخذ 5", "Take 10, 5 and 3") == {"numbers_missing": "the original's 3"}


def _cli(argv, capsys) -> tuple[int, dict]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def _shipped_batch(tmp_path, target: str, changes: dict[str, str]):
    shipped = builtin_translation_set(target)
    data = shipped.to_dict()
    data["entries"] = [
        dict(e, text=changes[e["id"]]) for e in data["entries"] if e["id"] in changes
    ]
    path = tmp_path / f"{target}.batch.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_check_entries_finds_every_bad_entry_of_a_real_target(tmp_path, capsys):
    shipped = builtin_translation_set("pmd-red")
    with_command = next(e for e in shipped.entries if re.search(r"\{[A-Z_]+\}", e.text))
    plain = [e for e in shipped.entries if "{" not in e.text and "\n" not in e.text]
    changes = {
        with_command.id: re.sub(r"\{[A-Z_]+\}", "", with_command.text, count=1),
        plain[0].id: plain[0].text + " Hello",
        plain[1].id: "ً" + plain[1].text,
        plain[2].id: plain[2].text,
    }
    code, report = _cli(
        ["targets", "check-entries", "pmd-red", str(_shipped_batch(tmp_path, "pmd-red", changes))],
        capsys,
    )

    assert code == 1 and report["target"] == "pmd-red" and report["baseline"] == "shipped"
    assert report["changed"] == 3 and report["entries"] == 4
    found = {e["id"]: e["code"] for e in report["errors"]}
    assert found == {
        with_command.id: "TOKEN_ORDER_VIOLATION",
        plain[0].id: "UNENCODABLE_TEXT",
        plain[1].id: "UNSUPPORTED_ARABIC_MARK",
    }


def test_check_entries_of_the_shipped_file_passes_without_a_run(tmp_path, capsys):
    path = tmp_path / "advance-wars.json"
    path.write_text(builtin_translation_set("advance-wars").dumps(), encoding="utf-8")
    code, report = _cli(["targets", "check-entries", "advance-wars", str(path)], capsys)

    assert code == 0 and report["ok"] is True and report["runs"] == 0
    assert report["errors"] == [] and report["group_errors"] == []


def test_check_entries_reports_entries_that_overflow_a_shared_budget_together(tmp_path, capsys):
    # Each briefing keeps within Gran Turismo's free glyph codes alone; together
    # their extra letter forms pass the budget.
    first = " ببب تتت ثثث ججج ححح خخخ سسس ششش صصص ضضض ططط ب ت ث ج ح خ س ش ص ض ط"
    second = " ظظظ ععع غغغ ففف ققق ككك للل ممم ننن ههه ييي ظ ع غ ف ق ك ل م ن ه ي بد بذ بر بز بو بة ٠١٢٣٤٥٦٧٨٩"
    shipped = {entry.id: entry for entry in builtin_translation_set("gran-turismo").entries}
    a, b = shipped["license.b1"], shipped["license.b3"]
    path = _shipped_batch(tmp_path, "gran-turismo", {a.id: a.text + first, b.id: b.text + second})
    code, report = _cli(["targets", "check-entries", "gran-turismo", str(path)], capsys)

    assert code == 1 and report["errors"] == []
    (group,) = report["group_errors"]
    assert (group["id"], group["with"]) == (b.id, [a.id])
    assert group["code"] == "ARABIC_GLYPH_CAPACITY_EXCEEDED"


def test_check_entries_takes_a_baseline_and_refuses_what_it_cannot_do(tmp_path, capsys):
    shipped = builtin_translation_set("advance-wars")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(shipped.dumps(), encoding="utf-8")
    entry = shipped.entries[0]
    path = _shipped_batch(tmp_path, "advance-wars", {entry.id: entry.text})
    code, report = _cli(
        ["targets", "check-entries", "advance-wars", str(path), "--baseline", str(baseline)],
        capsys,
    )
    assert code == 0 and report["baseline"] == str(baseline) and report["changed"] == 0

    # A baseline is complete and passes: one batch of the file is not one.
    partial = _shipped_batch(tmp_path / "..", "advance-wars", {entry.id: entry.text})
    argv = ["targets", "check-entries", "advance-wars", str(path), "--baseline", str(partial)]
    assert main(argv) == 2
    assert "does not pass advance-wars's check" in capsys.readouterr().err

    assert main(["targets", "check-entries", "advance-wars", str(path), "--max-runs", "0"]) == 2
    assert "--max-runs" in capsys.readouterr().err
    assert main(["targets", "check-entries", "pmd-red", str(path)]) == 2
    assert "not pmd-red" in capsys.readouterr().err


def test_glossary_terms_come_from_the_batch_or_the_baseline(tmp_path):
    baseline = replace(_baseline(), glossary=(GlossaryTerm("Mila", "ميلا"),))
    path = _write(tmp_path, [{"id": "line.0", "text": "نص", "source": "Mila"}])
    report = entry_report(_check, load_batch(path, "demo", baseline), None, max_runs=10)
    assert [w["kind"] for w in report["warnings"]] == ["glossary"]
