# Translation Document and Token Model

Version: 1

## Goal

Classic Retro needs one translation representation that works across very different game engines.

A translator must be able to change human language without accidentally deleting or mutating engine instructions such as:

- player-name variables,
- item or location placeholders,
- waits and pauses,
- color or speed commands,
- explicit line/page breaks,
- unknown but required binary opcodes.

## Design basis

XLIFF 2.1 explicitly separates linguistic text from inline codes such as formatting instructions and variable placeholders.

Reference:
- https://docs.oasis-open.org/xliff/xliff-core/v2.1/xliff-core-v2.1.html

ICU MessageFormat likewise treats a message as one translatable unit containing placeholders, so translators can move variable elements according to target-language grammar rather than translating disconnected fragments.

Reference:
- https://unicode-org.github.io/icu/userguide/format_parse/messages/

Classic Retro borrows those principles but does not use XLIFF or ICU MessageFormat as its canonical storage format because retro-game control codes are engine-specific and sometimes opaque binary values.

## Canonical format

The source of truth is UTF-8 JSON validated by JSON Schema.

JSON was selected for the foundation because:

- the project already ships versioned JSON Schemas,
- it has deterministic machine parsing,
- it avoids inventing an escaping grammar for arbitrary game opcodes,
- future editor/UI or XLIFF import/export can sit above the same canonical model.

## Token streams

Each source and target message is a sequence of typed tokens.

Example:

```json
{
  "id": "intro.001",
  "source": {
    "tokens": [
      {"type": "text", "text": "Welcome, "},
      {
        "type": "variable",
        "id": "player",
        "name": "PLAYER",
        "movement": "free"
      },
      {"type": "text", "text": "!"},
      {
        "type": "control",
        "id": "wait",
        "name": "WAIT",
        "movement": "ordered",
        "args": {"frames": 30}
      }
    ]
  },
  "target": {
    "tokens": [
      {"type": "text", "text": "مرحبًا بك يا "},
      {
        "type": "variable",
        "id": "player",
        "name": "PLAYER",
        "movement": "free"
      },
      {"type": "text", "text": "!"},
      {
        "type": "control",
        "id": "wait",
        "name": "WAIT",
        "movement": "ordered",
        "args": {"frames": 30}
      }
    ]
  }
}
```

## Token types

### text

Visible language. Only text tokens are translated freely.

### variable

Runtime content inserted by the game, for example PLAYER, ITEM, MONEY, or LOCATION.

### control

An engine command such as WAIT, COLOR, SPEED, SOUND, or another named opcode understood by an Engine Adapter.

### line_break / page_break

Explicit layout/control boundaries that belong to the game script rather than to ordinary Unicode text.

### opaque

A required binary command that has not yet been given a semantic name.

Opaque tokens carry hexadecimal bytes so extraction/rebuild can remain lossless while reverse engineering continues.

## Stable inline IDs

Every non-text token has an ID unique inside one message.

The source and target must contain exactly the same protected IDs.

This prevents a translator or tool from silently losing an instruction.

## Movement policy

Every inline token declares one of two policies.

### free

The token may move in the target sentence.

Typical use: a runtime variable such as the player name.

### ordered

The token may be surrounded by different translated text, but its relative order against other ordered tokens must remain unchanged.

Typical use: WAIT, PAGE BREAK, audio commands, or opaque engine operations.

This provides useful translator freedom without pretending every game opcode is safe to reorder.

## Definition preservation

Matching IDs are not enough.

For each protected token, Classic Retro also requires the target to preserve:

- token type,
- movement policy,
- semantic name,
- arguments,
- opaque bytes when present.

Changing WAIT 30 frames into WAIT 60 frames is therefore rejected by translation validation.

Game-specific tooling may later expose an explicit transformation workflow for commands that are intentionally editable. Ordinary translation must not mutate them accidentally.

## Entry states

Entries support:

- draft
- reviewed
- final

A final entry containing visible source text cannot have an empty visible target.

## Validation command

```text
classic-retro translation validate translation.json
```

Validation covers:

- JSON Schema,
- duplicate entry IDs,
- duplicate protected token IDs,
- exact protected-token set,
- protected-token definitions,
- relative order of ordered tokens,
- basic final-entry completeness.

Arabic shaping, bidi resolution, glyph mapping, and pixel-width layout are later pipeline stages. They must consume this validated logical document rather than changing its semantic token structure.
