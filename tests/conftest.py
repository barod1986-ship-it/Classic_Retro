"""Fixtures shared by the test modules.

``reference_font`` is the pinned reference font a few tests draw with. It is never
bundled with the tests: the fixture reads its path from the environment variable
``CLASSIC_RETRO_REFERENCE_FONT`` and skips the test when that is unset, so a bare
checkout runs the whole suite and a configured one also checks the shipped script
against the real font.

``demo_targets`` is the harness the localization tests build invented targets with:
a no-op CLI registration, a ``LocalizationTarget`` factory with every field filled
and a runner that drives the ``targets`` commands through a fresh parser. The
callables are stateless, so the fixture is made once per session.

pyproject passes ``--import-mode=importlib``, under which the test modules are not
importable from one another; pytest still loads this ``conftest.py`` by path, so
the fixtures reach every module under ``tests/`` without an import.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from classic_retro.localization.commands import register_cli
from classic_retro.localization.targets import LocalizationTarget, TargetRegistry


@pytest.fixture
def reference_font() -> Path:
    """The pinned reference font, from the environment; never bundled with the tests."""
    path = os.environ.get("CLASSIC_RETRO_REFERENCE_FONT")
    if not path:
        pytest.skip("CLASSIC_RETRO_REFERENCE_FONT is unset")
    return Path(path)


def _no_cli(_: argparse._SubParsersAction) -> None:
    return None


def _target(target_id: str = "demo", **changes) -> LocalizationTarget:
    fields = {
        "id": target_id,
        "game_id": f"{target_id}-game",
        "title": "Demo Game",
        "platform_id": "gba",
        "kind": "rom-overlay",
        "strategies": ("glyph-font",),
        "scope": "a demo",
        "guide": "docs/DEMO.md",
        "notes": "docs/DEMO_NOTES.md",
        "register_cli": _no_cli,
    }
    return LocalizationTarget(**{**fields, **changes})


def _run(registry: TargetRegistry, argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    register_cli(parser.add_subparsers(dest="command", required=True), registry)
    args = parser.parse_args(argv)
    return args.handler(args)


@dataclass(frozen=True, slots=True)
class DemoTargets:
    """The three callables of the demo-target harness.

    ``no_cli`` registers nothing and is the ``register_cli`` of every target
    ``target`` makes; ``target`` is a rom overlay of an invented GBA game called
    ``demo`` unless a field is overridden; ``run`` parses ``argv`` with the
    ``targets`` commands registered against a registry and returns the exit code.
    """

    no_cli: Callable[[argparse._SubParsersAction], None]
    target: Callable[..., LocalizationTarget]
    run: Callable[[TargetRegistry, list[str]], int]


@pytest.fixture(scope="session")
def demo_targets() -> DemoTargets:
    """The demo-target harness, shared by the localization and digest tests."""
    return DemoTargets(no_cli=_no_cli, target=_target, run=_run)
