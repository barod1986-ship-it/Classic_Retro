"""Build src/classic_retro/translations/polished-crystal.json from a translation in progress.

The Polished Crystal translation is written outside the repository, in batches
of ``{id: arabic}`` files (the translators' workspaces hold the game's text, so
they stay local). This script gathers them into the target's translation file:

    python tools/polished_crystal_translations.py \\
        --fill glossary_fill.json --batches 'batches/batch-*.ar.json' \\
        --glossary-dir glossary --source path/to/pristine/polishedcrystal \\
        [--labels labels.json] [--out src/classic_retro/translations/polished-crystal.json]

- ``--fill`` and ``--batches``: ``{id: arabic}`` files; a later file wins, and
  the batches win over the fill (the names the glossary filled in).
- ``--glossary-dir``: the ``*.ar.json`` name lists (``[{"en", "ar"}]``): the
  names of species, moves, items, places, classes and trainers become the
  file's glossary (a term written two ways is left out, as are menu words).
- ``--source`` (a pristine checkout) or ``--contexts`` (what
  ``classic-retro polished-crystal make-manifest --contexts`` wrote): each
  entry's context, from the extractor.
- ``--labels``: ``{id: arabic}`` of the entries the manifest does not hold
  (the Pokédex's tilemap labels and the key phrase); without it they are kept
  from the existing output file.

Each entry is checked as ``targets check-translations`` checks it; an entry that
fails, or whose id the manifest no longer has, is left out and listed in
``--rejects`` (default: ``polished-crystal.rejects.json`` in the current folder) so it can be
fixed in its batch. Run ``classic-retro targets check-translations
polished-crystal --font FONT --preview-dir DIR --update-digests`` afterwards:
the digests follow the translation.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

from classic_retro.localization.translations import (
    GlossaryTerm,
    Translation,
    TranslationSet,
    load_translation_set,
)
from classic_retro.source.polished_crystal import dex, encode
from classic_retro.source.polished_crystal.inject import group_growth, ngram_leaves
from classic_retro.source.polished_crystal.manifest import builtin_manifest
from classic_retro.source.polished_crystal_arabic import (
    KEY_PHRASE_ID,
    TARGET,
    _check_key_phrase,
    extra_entries,
    make_manifest,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "src" / "classic_retro" / "translations" / f"{TARGET}.json"

NOTATION = (
    "Logical Arabic in the overlay's notation (source/polished_crystal/encode.py), written as "
    "it reads: the build shapes the letters, picks each glyph and the game draws the text from "
    "the right. Arabic letters (no Persian letters), no vowel marks, no tatweel, no Latin letters "
    'and no brackets; the signs are space . ، ؛ ؟ ! : - … « » " / × % + ¥ ♂ ♀ & ♪ ♥ and the '
    "digits 0-9 or ٠-٩ (all quotation marks become one neutral quote, ؛ becomes ،). "
    "\\p starts a new page of the speech box (the game waits for the button), only in a speech-box "
    "text (kind dialog); \\n forces a line break where the entry allows lines; \\f starts a new "
    "page of a box that has pages (the Pokédex's description). The build wraps every line itself: "
    "18 cells in the speech box, the entry's width elsewhere, and refuses a text that does not "
    "fit its box, its field or its bytes. Placeholders keep their count (their order may change): "
    "{PLAYER} {RIVAL} {TRENDY} (a name of up to 7 letters), {USER} {TARGET} (a Pokémon in battle, "
    "the game adds the word for the foe's after it), {ENEMY} (a trainer's class and name, a line "
    "of its own), {ram:SYMBOL} (a name or item the game writes), {num:SYMBOL,BYTES,DIGITS} (a "
    "number), {d:CONST} (a number fixed at build time), {wait} {pause} {sound:SFX} {day} "
    "{far:LABEL} (the game's text commands, in speech-box texts only); {LV} {PK} {MN} {ID} {No} "
    "are tiles of the English font a translation may drop. The player's gender: {masculine|"
    "feminine} holds the words that differ (letters, spaces and signs only, no placeholder), and "
    "the game shows the side that fits the player. Every entry needs its Arabic: the Arabic "
    "glyphs take the Latin letters' codes, so a text left in English would show as wrong letters; "
    "an empty text only where an entry's limits allow it."
)
# The glossary keeps the names a translator needs everywhere: places, types, badges, the main
# characters and the core terms. Whole name tables (species, moves, items, abilities, trainers) are
# entries of their own, so they are not repeated here.
GLOSSARY_LISTS = ("types", "landmarks", "badges")
GLOSSARY_CHARACTERS = frozenset(
    {
        "Falkner", "Bugsy", "Whitney", "Morty", "Chuck", "Jasmine", "Pryce", "Clair",
        "Will", "Koga", "Bruno", "Karen", "Lance", "Brock", "Misty", "Surge", "Erika",
        "Janine", "Sabrina", "Blaine", "Blue", "Red", "Lyra", "Kurt", "Bill", "Eusine",
        "Kimono Girl", "Proton", "Petrel", "Ariana", "Archer", "Giovanni", "Mr. Pokémon",
    }
)  # fmt: skip
CORE_TERMS = (
    ("Pokémon", "بوكيمون"),
    ("Poké Ball", "كرة بوكي"),
    ("Pokédex", "بوكيديكس"),
    ("Pokégear", "بوكيغير"),
    ("Pokémon Center", "مركز البوكيمون"),
    ("Poké Mart", "متجر بوكي"),
    ("Trainer", "مدرب"),
    ("Gym", "صالة"),
    ("Gym Leader", "قائد الصالة"),
    ("Badge", "شارة"),
    ("Elite Four", "النخبة الأربعة"),
    ("Champion", "البطل"),
    ("Team Rocket", "فريق الصاروخ"),
    ("Professor Elm", "البروفيسور إلم"),
    ("Professor Oak", "البروفيسور أوك"),
)


def _load_texts(paths: list[str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for pattern in paths:
        matches = sorted(glob.glob(pattern)) or [pattern]
        for path in matches:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise SystemExit(f"{path}: expected an object of id -> Arabic")
            texts.update({key: value for key, value in data.items() if isinstance(value, str)})
    return texts


def _glossary(directory: Path, texts: dict[str, str]) -> list[GlossaryTerm]:
    seen: dict[str, str] = dict(CORE_TERMS)
    conflicting: set[str] = set()
    lists = [*GLOSSARY_LISTS, "trainer_names"]
    for name in lists:
        path = directory / f"{name}.ar.json"
        if not path.exists():
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            term = str(item.get("en", "")).replace("\\n", " ").strip()
            if name == "trainer_names" and term not in GLOSSARY_CHARACTERS:
                continue
            arabic = str(item.get("ar", "")).replace("\\n", " ").strip()
            if len(term) < 3 or not re.search("[A-Za-z]{2}", term) or term.startswith("<"):
                continue
            if not arabic or re.search("[A-Za-z]", arabic):
                continue
            if term in seen and seen[term] != arabic:
                conflicting.add(term)
            seen.setdefault(term, arabic)
    used = " ".join(texts.values())
    return [
        GlossaryTerm(term, arabic)
        for term, arabic in sorted(seen.items(), key=lambda item: item[0].casefold())
        if term not in conflicting and arabic in used
    ]


def _context(text: str) -> str:
    # Contexts name places and layouts; a quoted phrase may be the game's: drop it.
    text = re.sub(r'"[^"]*[A-Za-z][^"]*"|“[^”]*”', "…", text)
    return re.sub(r"\s+", " ", text).strip() or "A text of the game"


def check_one(entry_id: str, text: str) -> list[str]:
    """Why an entry is refused, as check-translations would say (empty when it passes)."""
    manifest = builtin_manifest()
    if entry_id in dex.label_entries():
        try:
            dex.check_label(entry_id, text)
        except Exception as exc:  # noqa: BLE001
            return [str(exc)]
        return []
    if entry_id == KEY_PHRASE_ID:
        try:
            _check_key_phrase(text)
        except Exception as exc:  # noqa: BLE001
            return [str(exc)]
        return []
    if entry_id not in manifest.entries:
        return ["the manifest has no entry of this id"]
    return encode.check(manifest.entries[entry_id], text, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fill", action="append", default=[], help="{id: arabic} file(s)")
    parser.add_argument("--batches", action="append", default=[], help="{id: arabic} files (glob)")
    parser.add_argument(
        "--labels", type=Path, help="{id: arabic} of the entries outside the manifest"
    )
    parser.add_argument("--glossary-dir", type=Path)
    parser.add_argument("--source", type=Path, help="A pristine checkout (for the contexts)")
    parser.add_argument("--contexts", type=Path, help="make-manifest --contexts output")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--rejects", type=Path)
    args = parser.parse_args(argv)

    manifest = builtin_manifest()
    texts = _load_texts(args.fill)
    texts.update(_load_texts(args.batches))
    extras = extra_entries()
    if args.labels is not None:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
    elif args.out.exists():
        existing = load_translation_set(args.out, TARGET)
        labels = {entry.id: entry.text for entry in existing.entries if entry.id in extras}
    else:
        labels = {}
    for entry_id in extras:
        if entry_id in labels:
            texts[entry_id] = labels[entry_id]
    if args.contexts is not None:
        contexts = json.loads(args.contexts.read_text(encoding="utf-8"))
    elif args.source is not None:
        contexts = make_manifest(args.source)[1]
    else:
        raise SystemExit("give --source (a pristine checkout) or --contexts")

    rejects: dict[str, object] = {}
    accepted: dict[str, str] = {}
    for entry_id, text in texts.items():
        allow_empty = manifest.entries.get(entry_id, {}).get("limits", {}).get("allow_empty")
        if not text.strip() and not allow_empty:
            continue
        problems = check_one(entry_id, text)
        if problems:
            rejects[entry_id] = problems
        else:
            accepted[entry_id] = text
    # Strings of a one-byte offset table share its room: refuse the table's last ones.
    encoded = {}
    leaves = ngram_leaves(manifest, accepted)
    for entry_id in manifest.entries:
        if entry_id in accepted:
            encoded[entry_id] = encode.encode(
                manifest.entries[entry_id], accepted[entry_id], leaves
            )
    for group, (growth, slack) in group_growth(manifest, encoded).items():
        if growth > slack:
            for member in reversed(manifest.groups[group]["members"]):
                if member in accepted and growth > slack:
                    rejects[member] = [
                        f"{group}: the table's strings outgrow it ({growth} > {slack})"
                    ]
                    del accepted[member]
                    growth = group_growth(
                        manifest, {k: v for k, v in encoded.items() if k in accepted}
                    ).get(group, (0, slack))[0]
    missing = [entry_id for entry_id in extras if entry_id not in accepted]
    if missing:
        raise SystemExit("no (valid) Arabic for " + ", ".join(missing) + "; give --labels")

    entries = [
        Translation(entry_id, accepted[entry_id], context=_context(contexts.get(entry_id, "")))
        for entry_id in manifest.entries
        if entry_id in accepted
    ]
    entries += [
        Translation(entry_id, accepted[entry_id], context=description)
        for entry_id, description in extras.items()
    ]
    glossary = _glossary(args.glossary_dir, accepted) if args.glossary_dir else []
    translations = TranslationSet(TARGET, NOTATION, tuple(entries), tuple(glossary))
    args.out.write_text(translations.dumps(), encoding="utf-8")
    # Never next to the output: the translations folder holds translation files only.
    rejects_path = args.rejects or Path.cwd() / f"{TARGET}.rejects.json"
    if rejects:
        rejects_path.write_text(
            json.dumps(rejects, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "translations": str(args.out),
                "entries": len(entries),
                "manifest_entries": len(manifest),
                "untranslated": sum(entry_id not in accepted for entry_id in manifest.entries),
                "glossary": len(glossary),
                "rejected": len(rejects),
                "rejects": str(rejects_path) if rejects else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
