"""``targets split`` and ``targets merge``: a script translated in batches."""

from __future__ import annotations

import json

import pytest

from classic_retro.cli import main
from classic_retro.core.errors import ClassicRetroError
from classic_retro.localization.batches import merge_translations, split_translations
from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    builtin_translation_set,
    load_translation_set,
)


def _workspace(count: int = 5) -> TranslationSet:
    """An invented target's workspace: entry n's original names Mila when n is even."""
    entries = tuple(
        Translation(
            f"line.{n}",
            f"نص {n}",
            context="an invented line",
            source=f"Line {n}" + (" for Mila" if n % 2 == 0 else ""),
        )
        for n in range(count)
    )
    return TranslationSet(
        "demo",
        "plain text",
        entries,
        glossary=(GlossaryTerm("Mila", "ميلا"), GlossaryTerm("Tom", "توم")),
        workspace_from="an invented image",
    )


def test_split_cuts_batches_in_order_with_the_glossary_their_originals_name():
    batches = split_translations(_workspace(), 2)

    assert [[e.id for e in batch.entries] for batch in batches] == [
        ["line.0", "line.1"],
        ["line.2", "line.3"],
        ["line.4"],
    ]
    assert all(batch.is_workspace for batch in batches)
    assert [[t.term for t in batch.glossary] for batch in batches] == [["Mila"]] * 3

    (only,) = split_translations(_workspace(), 10, ["line.[13]"])
    assert [e.id for e in only.entries] == ["line.1", "line.3"] and only.glossary == ()

    committed = TranslationSet(
        "demo", "plain text", _workspace().entries[:2], _workspace().glossary
    )
    assert split_translations(committed, 1)[0].glossary == committed.glossary

    with pytest.raises(ClassicRetroError, match="at least one"):
        split_translations(_workspace(), 0)
    with pytest.raises(ClassicRetroError, match="No entry of demo matches nothing.*"):
        split_translations(_workspace(), 2, ["nothing.*"])


def test_merge_puts_text_and_notes_back_and_adds_new_terms():
    workspace = _workspace()
    first, second, third = split_translations(workspace, 2)
    first = TranslationSet(
        "demo",
        "plain text",
        (
            Translation("line.0", "سطر", notes="shorter"),
            Translation("line.1", "نص 1"),
        ),
        glossary=(GlossaryTerm("Mila", "ميلا"), GlossaryTerm("Rex", "ركس")),
    )
    merged, report = merge_translations(workspace, [first, third])

    assert report == {"merged": 3, "changed": ["line.0"], "glossary_added": ["Rex"]}
    by_id = {entry.id: entry for entry in merged.entries}
    assert by_id["line.0"].text == "سطر" and by_id["line.0"].notes == "shorter"
    # The workspace keeps its originals, contexts and order.
    assert by_id["line.0"].source == "Line 0 for Mila" and by_id["line.0"].context
    assert [e.id for e in merged.entries] == [e.id for e in workspace.entries]
    assert merged.is_workspace and [t.term for t in merged.glossary] == ["Mila", "Tom", "Rex"]


def test_merge_refuses_unknown_repeated_and_conflicting_entries():
    workspace = _workspace()
    stray = TranslationSet("demo", "plain text", (Translation("ghost", "شبح"),))
    clash = TranslationSet(
        "demo",
        "plain text",
        (Translation("line.0", "سطر"),),
        glossary=(GlossaryTerm("Mila", "ميلة"),),
    )
    with pytest.raises(ClassicRetroError) as refused:
        merge_translations(workspace, [stray, clash, clash])
    message = str(refused.value)
    assert "demo has no entry ghost" in message
    assert "in more than one batch: line.0" in message
    assert "Mila (ميلا / ميلة)" in message

    other = TranslationSet("other", "plain text", (Translation("line.0", "سطر"),))
    with pytest.raises(ClassicRetroError, match="of other, not demo"):
        merge_translations(workspace, [other])


def test_split_and_merge_commands_round_trip_a_file(tmp_path, capsys):
    shipped = builtin_translation_set("advance-wars")
    source = tmp_path / "advance-wars.json"
    source.write_text(shipped.dumps(), encoding="utf-8")
    out_dir = tmp_path / "batches"

    assert main(["targets", "split", str(source), "--size", "5", "--out-dir", str(out_dir)]) == 0
    report = json.loads(capsys.readouterr().out)
    files = [batch["file"] for batch in report["batches"]]
    assert report["entries"] == len(shipped.entries) and report["workspace"] is False
    assert [p.name for p in sorted(out_dir.iterdir())] == [
        f"advance-wars.batch-{n:03d}.json" for n in range(1, len(files) + 1)
    ]
    # Batch files are not replaced without --force.
    assert main(["targets", "split", str(source), "--out-dir", str(out_dir)]) == 2
    assert "OUTPUT_EXISTS" in capsys.readouterr().err

    batch = json.loads(open(files[0], encoding="utf-8").read())
    batch["entries"][0]["text"] = "نص جديد"
    open(files[0], "w", encoding="utf-8").write(json.dumps(batch, ensure_ascii=False))
    merged = tmp_path / "merged.json"
    assert main(["targets", "merge", str(source), *files, "--out", str(merged)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["merged"] == len(shipped.entries) and report["changed"] == [shipped.entries[0].id]
    entries = load_translation_set(merged, "advance-wars").entries
    assert entries[0].text == "نص جديد" and entries[1:] == shipped.entries[1:]

    assert main(["targets", "merge", str(source), *files, "--out", str(merged)]) == 2
    assert "OUTPUT_EXISTS" in capsys.readouterr().err


def test_a_forced_split_leaves_no_batch_of_an_earlier_one(tmp_path, capsys):
    source = tmp_path / "advance-wars.json"
    source.write_text(builtin_translation_set("advance-wars").dumps(), encoding="utf-8")
    out_dir = tmp_path / "batches"
    assert main(["targets", "split", str(source), "--size", "2", "--out-dir", str(out_dir)]) == 0
    earlier = sorted(path.name for path in out_dir.iterdir())
    capsys.readouterr()

    # Fewer batches now: the earlier ones past them would be merged back too.
    argv = ["targets", "split", str(source), "--size", "5", "--out-dir", str(out_dir)]
    assert main(argv) == 2
    assert "OUTPUT_EXISTS" in capsys.readouterr().err
    assert sorted(path.name for path in out_dir.iterdir()) == earlier

    assert main([*argv, "--force"]) == 0
    files = [batch["file"] for batch in json.loads(capsys.readouterr().out)["batches"]]
    assert sorted(str(path) for path in out_dir.iterdir()) == sorted(files)
