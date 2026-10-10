from __future__ import annotations

import json

import pytest

from classic_retro.adapters.registry import build_registry
from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source.polishedcrystal_catalog import (
    SOURCE_COMMIT,
    check_workspace,
    scan_source,
    validate_translation,
    without_comment,
    write_catalog,
)


def _source(tmp_path):
    source = tmp_path / "polishedcrystal"
    source.mkdir()
    (source / "Makefile").write_text("VERSION := 3.2.3\n", encoding="utf-8")
    (source / "maps").mkdir()
    (source / "data").mkdir()
    (source / "maps" / "Intro.asm").write_text(
        'OakText:: text "Welcome, <PLAYER>!" ; "comment only"\n'
        '    line "Hello; world!"\n'
        '    cont "Is that so?"\n'
        "    done\n"
        'DisplayMenu: db "YES@" ; marker\n'
        '    dw "symbolic" ; requires classification review\n',
        encoding="utf-8",
    )
    return source


def test_revision_and_engine_registered():
    registry = build_registry(load_external=False)
    adapter = registry.games["polished-crystal-323"]
    assert adapter.platform_id == "gbc"
    assert adapter.engine_id in registry.engines
    assert adapter.revisions[0].sha256 == (
        "f06dbebe3fd20db54e7804605f7a55ad05b8ca203c62209705290d8880864803"
    )
    assert adapter.revisions[0].size == 2_097_152
    assert adapter.source_build.commit == SOURCE_COMMIT


def test_source_catalog_records_all_strings_without_comments(tmp_path):
    source = _source(tmp_path)
    catalog = scan_source(source, strict=False)
    assert catalog["files_scanned"] == 1
    assert catalog["count"] == 5
    assert catalog["categories"] == {"dialogue": 3, "review": 1, "string": 1}
    assert catalog["source_verified"] is False
    assert catalog["entries"][0]["id"] == "maps/Intro.asm:1:0"
    assert catalog["entries"][0]["directive"] == "text"
    assert catalog["entries"][0]["source"] == "Welcome, <PLAYER>!"
    assert catalog["entries"][1]["source"] == "Hello; world!"
    assert not any("comment only" in e["source"] for e in catalog["entries"])
    assert without_comment('db "A; B" ; comment') == 'db "A; B" '


def test_source_is_pinned_and_modified_version_refused(tmp_path):
    source = _source(tmp_path)
    with pytest.raises(ClassicRetroError) as caught:
        scan_source(source)  # incomplete source tree does not claim to be the real v3.2.3
    assert caught.value.code is ErrorCode.SOURCE_BASELINE_MISMATCH
    (source / "Makefile").write_text("VERSION := 3.2.2\n", encoding="utf-8")
    with pytest.raises(ClassicRetroError):
        scan_source(source, strict=False)


def test_preserve_runtime_placeholders_and_controls():
    assert validate_translation("Hi, <PLAYER>!@", "مرحبًا، <PLAYER>!@") == []
    assert "runtime placeholders changed" in validate_translation(
        "Hi, <PLAYER>!", "مرحبًا، <RIVAL>!"
    )
    assert "@ terminator count changed" in validate_translation("Hello@", "مرحبًا")
    assert "no Arabic text" in validate_translation("Hello", "Hello")


def test_workspace_cannot_claim_full_translation_without_review(tmp_path):
    source = _source(tmp_path)
    catalog = scan_source(source, strict=False)
    catalog["entries"][0]["arabic"] = "مرحبًا، <PLAYER>!"
    catalog["entries"][1]["arabic"] = "أهلًا بالعالم!"
    catalog["entries"][2]["arabic"] = "أحقًا؟"
    catalog["entries"][3]["arabic"] = "نعم@"
    report = check_workspace(source, catalog, strict=False)
    assert report["translated"] == 4
    assert report["remaining"] == 1
    assert report["renderer_ready"] is False
    assert report["complete"] is False
    catalog["entries"][4]["review"] = "not_text"
    assert check_workspace(source, catalog, strict=False)["complete"] is True
    catalog["entries"][0]["source"] = "tampered"
    assert "source drift: source" in [
        issue["problem"] for issue in check_workspace(source, catalog, strict=False)["errors"]
    ]


def test_workspace_refuses_deleted_ids_and_duplicate_ids(tmp_path):
    source = _source(tmp_path)
    catalog = scan_source(source, strict=False)
    catalog["entries"].pop()
    report = check_workspace(source, catalog, strict=False)
    assert report["missing_entries"] == 1
    assert report["complete"] is False
    catalog["entries"].append(catalog["entries"][0].copy())
    report = check_workspace(source, catalog, strict=False)
    assert any(entry["problem"] == "duplicate ID" for entry in report["errors"])


def test_never_overwrite_catalog(tmp_path, monkeypatch):
    source = _source(tmp_path)
    output = tmp_path / "catalog.json"
    # The synthetic test fixture has no upstream files, so bypass only that guard.
    from classic_retro.source import polishedcrystal_catalog as catalog_module

    monkeypatch.setattr(catalog_module, "_verify_upstream", lambda root: None)
    catalog = scan_source(source, strict=False)
    output.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ClassicRetroError) as caught:
        write_catalog(source, output)
    assert caught.value.code is ErrorCode.OUTPUT_EXISTS
