# Foundation Decisions

Date: 2026-09-23

This document records why the first executable foundation uses the current tools. These choices can be revisited when real platform work provides evidence that a different option is better.

## Python 3.11+

Classic Retro begins in Python because the early workload is dominated by binary inspection, deterministic file transforms, schema validation, scripting, tooling integration, and rapid adapter development.

Python 3.11 is the minimum supported version. This keeps the project compatible with several maintained Python generations while giving the core modern standard-library features.

Python 3.14 is also tested because it is the current stable Python line at the time of this decision.

References:
- https://docs.python.org/3/
- https://docs.python.org/3/whatsnew/3.14.html

## src package layout

The importable package lives under src/classic_retro/.

PyPA documents the src layout as a way to prevent accidental imports from the repository root, and current pytest guidance recommends it for new projects.

References:
- https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
- https://docs.pytest.org/en/stable/explanation/goodpractices.html

## pyproject.toml

Project metadata and tool configuration live in pyproject.toml, following current Python packaging standards.

Reference:
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

## Hatchling build backend

Hatchling is used only as the standards-compliant build backend. The project is not coupled to the Hatch environment manager.

Reference:
- https://hatch.pypa.io/latest/config/build/

## Standard-library argparse

The initial CLI uses argparse instead of adding a CLI framework. Python documents it as the default recommended standard-library module for basic command-line applications and it supports subcommands.

If future UX requirements exceed it, the CLI layer can be replaced without changing the core.

Reference:
- https://docs.python.org/3/library/argparse.html

## JSON Schema 2020-12

Versioned project documents use JSON Schema Draft 2020-12. The JSON Schema project identifies 2020-12 as the current published specification.

The Python jsonschema implementation supports Draft 2020-12 directly.

References:
- https://json-schema.org/specification
- https://python-jsonschema.readthedocs.io/

## pytest

Tests live outside application code under tests/, and pytest uses importlib import mode.

Reference:
- https://docs.pytest.org/en/stable/explanation/goodpractices.html

## Ruff

Ruff handles linting and formatting from one configuration in pyproject.toml. This avoids maintaining separate formatter/import-sort/linter stacks during the foundation phase.

References:
- https://docs.astral.sh/ruff/configuration/
- https://docs.astral.sh/ruff/formatter/

## Cross-platform CI

The foundation is tested on both Windows and Linux and on the oldest and newest supported Python lines. This is intentional: Classic Retro is a desktop tooling project that must not accidentally become Unix-only.

## What is intentionally absent

There is no GUI, no ROM parsing logic, no platform-specific implementation, no Arabic reshaper, and no emulator automation yet.

Those choices require their own research step and should only be added when their interfaces can be based on a real reference game or a proven cross-platform requirement.
