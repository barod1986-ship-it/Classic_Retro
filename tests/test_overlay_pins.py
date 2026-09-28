"""Digests of every ROM overlay's pins, so a moved pin cannot pass unnoticed.

A ROM overlay's tests fabricate their images from the overlay's own
constants: the pinned addresses, the original bytes a site is checked
against, the hook code and its symbols (``IMAGE``, ``SITES``, ``HOOK_CODE``
and their kin, and the script module's tables). A refactor that moves a
pinned address or edits an original byte string therefore passes the suite
silently, since the fabricated image moves with it. This test serializes
every module-level constant in capitals of each overlay module and of its
``*_script`` sibling into one canonical JSON document, digests it, and holds
the digest to ``tests/data/overlay_pins.json`` (``{target_id: sha256}``), so
such a change fails until it is acknowledged.

To change a pin deliberately, regenerate the record in the same commit as
the change, so the review sees the digest move next to the constant that
moved::

    CLASSIC_RETRO_UPDATE_PINS=1 python -m pytest tests/test_overlay_pins.py

With that variable set to ``1`` the test rewrites the file instead of
asserting. The record also names every ROM overlay and nothing else: a new
target needs an entry, a removed one loses its entry.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import importlib
import json
import os
import re
from collections.abc import Mapping, Set
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

import classic_retro
from classic_retro.localization.targets import LocalizationTarget, build_target_registry

PINS_PATH = Path(__file__).with_name("data") / "overlay_pins.json"
PACKAGE = Path(classic_retro.__file__).resolve().parent
UPDATE_VARIABLE = "CLASSIC_RETRO_UPDATE_PINS"
# The repr of an object without one of its own names its memory address,
# which differs on every run: such a value cannot be digested.
MEMORY_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+>")


def _overlay_modules(target: LocalizationTarget) -> tuple[ModuleType, ...]:
    """The target's overlay module and, when it has one, its ``_script`` sibling.

    The overlay is found as ``test_localization`` finds it: the one
    ``classic_retro.rom`` module the target's builtin module imports.
    """
    builtin = importlib.import_module(target.build.__module__)
    (overlay,) = (
        value
        for value in vars(builtin).values()
        if isinstance(value, ModuleType) and value.__name__.startswith("classic_retro.rom.")
    )
    script_name = f"{overlay.__name__}_script"
    try:
        script = importlib.import_module(script_name)
    except ModuleNotFoundError as error:
        # Only the sibling's own absence is expected: a script module whose
        # imports are broken must fail here, not vanish from the digest.
        if error.name != script_name:
            raise
        return (overlay,)
    return overlay, script


def _key(key: object) -> str:
    """A mapping key as a string: an enum member by its name, the rest by ``str``."""
    if isinstance(key, enum.Enum):
        return f"{type(key).__name__}.{key.name}"
    return str(key)


def _canonical(value: object, where: str) -> object:
    """``value`` in the canonical JSON form the digest is taken over.

    Scalars stay as they are, bytes become hex, unordered collections are
    sorted, mappings get string keys, and a dataclass instance carries its
    class name with its fields, except a ``source`` Path (a hook program's
    assembly file: its location is not a pin). A Path is named relative to
    the package, so the digest is the same on every machine. ``where`` names
    the constant, for the message when a value cannot be digested.
    """
    if value is None or isinstance(value, bool):
        return value
    # Before the scalars: a StrEnum is a str, an IntEnum an int.
    if isinstance(value, enum.Enum):
        return {"enum": _key(value)}
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, bytes | bytearray):
        return {"bytes": bytes(value).hex()}
    if isinstance(value, Path):
        try:
            relative = value.resolve().relative_to(PACKAGE).as_posix()
        except ValueError:
            relative = value.name
        return {"path": relative}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {
            field.name: _canonical(getattr(value, field.name), f"{where}.{field.name}")
            for field in dataclasses.fields(value)
            if not (field.name == "source" and isinstance(getattr(value, field.name), Path))
        }
        return {"dataclass": type(value).__name__, "fields": fields}
    if isinstance(value, Mapping):
        items = {_key(key): _canonical(item, f"{where}[{key!r}]") for key, item in value.items()}
        assert len(items) == len(value), f"{where}: two keys stringify alike"
        return {"mapping": items}
    if isinstance(value, Set):
        elements = [_canonical(element, where) for element in value]
        return {"set": sorted(elements, key=lambda element: json.dumps(element, sort_keys=True))}
    if isinstance(value, tuple | list):
        return [_canonical(element, where) for element in value]
    if isinstance(value, ModuleType):
        return {"module": value.__name__}
    if isinstance(value, type):
        return {"class": f"{value.__module__}.{value.__qualname__}"}
    if callable(value):
        return {"callable": f"{value.__module__}.{value.__qualname__}"}
    # Whatever remains (a range, today) is digested by its repr, which for
    # the builtin types spells out the value. A repr that names a memory
    # address would differ on every run, so it is refused rather than recorded.
    text = repr(value)
    assert not MEMORY_ADDRESS.search(text), f"{where}: {text} cannot be digested"
    return {"repr": text}


def _constants(module: ModuleType) -> dict[str, object]:
    """The module's names in capitals, private ones included, in canonical form.

    A private table of addresses is a pin all the same; only dunder names are
    left out.
    """
    return {
        name: _canonical(value, f"{module.__name__}.{name}")
        for name, value in vars(module).items()
        if name.isupper() and not name.startswith("__")
    }


def _digest(document: object) -> str:
    """SHA-256 of the document in canonical JSON: sorted keys, no spaces, raw non-ASCII."""
    text = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pin_digest(target: LocalizationTarget) -> str:
    """The digest of every constant of the target's overlay and script modules."""
    return _digest({module.__name__: _constants(module) for module in _overlay_modules(target)})


def _current_digests() -> dict[str, str]:
    return {
        target.id: pin_digest(target)
        for target in build_target_registry(load_external=False)
        if target.kind == "rom-overlay"
    }


def _recorded_digests() -> dict[str, str]:
    return json.loads(PINS_PATH.read_text(encoding="utf-8"))


def _record(digests: Mapping[str, str]) -> None:
    """Write the record with sorted keys and a trailing newline, so diffs stay small."""
    PINS_PATH.parent.mkdir(exist_ok=True)
    PINS_PATH.write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_every_rom_overlay_pin_digest_matches_the_record():
    """Each ROM overlay digests as recorded; the record has no more and no fewer."""
    current = _current_digests()
    assert current, "no ROM overlay target is registered"
    if os.environ.get(UPDATE_VARIABLE) == "1":
        _record(current)
        return
    assert PINS_PATH.is_file(), f"{PINS_PATH.name} is missing: set {UPDATE_VARIABLE}=1 to record"
    recorded = _recorded_digests()
    differences = [
        f"{target_id}: pins changed (recorded {recorded[target_id]}, now {digest})"
        for target_id, digest in current.items()
        if target_id in recorded and recorded[target_id] != digest
    ]
    differences += [
        f"{target_id}: no digest recorded" for target_id in current if target_id not in recorded
    ]
    differences += [
        f"{target_id}: recorded, but no such ROM overlay target"
        for target_id in recorded
        if target_id not in current
    ]
    assert not differences, (
        f"Overlay pins differ from {PINS_PATH.name}; if the change is deliberate, "
        f"record it in the same commit with {UPDATE_VARIABLE}=1:\n" + "\n".join(differences)
    )
    text = PINS_PATH.read_text(encoding="utf-8")
    assert text == json.dumps(recorded, indent=2, sort_keys=True) + "\n"


class _Box(enum.StrEnum):
    BUBBLE = "bubble"
    MAP = "map"


@dataclass(frozen=True, slots=True)
class _Site:
    address: int
    original: bytes
    source: Path = Path("/nowhere/demo_hooks.s")


class _Opaque:
    pass


def _module(name: str, **names: object) -> ModuleType:
    module = ModuleType(name)
    vars(module).update(names)
    return module


def test_canonical_form_spells_out_every_kind_of_pin():
    hooks = PACKAGE / "rom" / "demo_arabic_hooks.s"
    assert _canonical(None, "x") is None and _canonical(True, "x") is True
    assert _canonical(0x08001234, "x") == 0x08001234 and _canonical("USA", "x") == "USA"
    assert _canonical(b"\x00\xff", "x") == {"bytes": "00ff"}
    assert _canonical(bytearray(b"\x01"), "x") == {"bytes": "01"}
    assert _canonical(_Box.MAP, "x") == {"enum": "_Box.MAP"}
    assert _canonical(hooks, "x") == {"path": "rom/demo_arabic_hooks.s"}
    assert _canonical(Path("/elsewhere/other_hooks.s"), "x") == {"path": "other_hooks.s"}
    assert _canonical(_Site(0x10, b"\xaa"), "x") == {
        "dataclass": "_Site",
        "fields": {"address": 0x10, "original": {"bytes": "aa"}},
    }
    assert _canonical((3, "a", b"b"), "x") == [3, "a", {"bytes": "62"}]
    assert _canonical(frozenset({3, 1, 2}), "x") == {"set": [1, 2, 3]}
    assert _canonical({_Box.BUBBLE: 1, 7: (2,), "b": {}}, "x") == {
        "mapping": {"_Box.BUBBLE": 1, "7": [2], "b": {"mapping": {}}}
    }
    assert _canonical(range(3), "x") == {"repr": "range(0, 3)"}
    assert _canonical(json, "x") == {"module": "json"}
    assert _canonical(_Site, "x") == {"class": f"{__name__}._Site"}
    assert _canonical(_module, "x") == {"callable": f"{__name__}._module"}
    with pytest.raises(AssertionError, match="demo.OPAQUE: <.*_Opaque object at 0x.*> cannot"):
        _canonical(_Opaque(), "demo.OPAQUE")
    with pytest.raises(AssertionError, match="demo.ALIKE: two keys stringify alike"):
        _canonical({1: "a", "1": "b"}, "demo.ALIKE")


def test_pin_digest_ignores_order_and_private_names_below_capitals_but_not_a_moved_pin():
    sites = (_Site(0x08001000, b"\x01\x02"), _Site(0x08002000, b"\x03"))
    module = _module(
        "demo",
        IMAGE_SIZE=0x400000,
        SITES=sites,
        CALLS=frozenset({0x08000010, 0x08000004}),
        ORIGINALS={"b": b"\x02", "a": b"\x01"},
        _PAGES={2: "second", 1: "first"},
        lower_case="ignored",
        __doc__="ignored too",
    )
    constants = _constants(module)
    assert set(constants) == {"IMAGE_SIZE", "SITES", "CALLS", "ORIGINALS", "_PAGES"}
    digest = _digest({"demo": constants})
    assert len(digest) == 64 and digest == _digest({"demo": dict(reversed(constants.items()))})
    reordered = _module(
        "demo",
        _PAGES={1: "first", 2: "second"},
        ORIGINALS={"a": b"\x01", "b": b"\x02"},
        CALLS=frozenset({0x08000004, 0x08000010}),
        SITES=sites,
        IMAGE_SIZE=0x400000,
        other_case="still ignored",
    )
    assert _digest({"demo": _constants(reordered)}) == digest
    moved = _module("demo", **{**vars(module), "SITES": (sites[0], _Site(0x08002004, b"\x03"))})
    assert _digest({"demo": _constants(moved)}) != digest
    edited = _module("demo", **{**vars(module), "ORIGINALS": {"a": b"\x01", "b": b"\x03"}})
    assert _digest({"demo": _constants(edited)}) != digest
    swapped = _module("demo", **{**vars(module), "SITES": (sites[1], sites[0])})
    assert _digest({"demo": _constants(swapped)}) != digest


def test_the_record_names_every_rom_overlay_once_with_a_full_digest():
    recorded = _recorded_digests()
    overlays = {
        target.id
        for target in build_target_registry(load_external=False)
        if target.kind == "rom-overlay"
    }
    assert set(recorded) == overlays
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in recorded.values())
