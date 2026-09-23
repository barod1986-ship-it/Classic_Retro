# Game Text Codec / Encoding Core

Version: 1

## Purpose

The translation model stores logical text and protected tokens. The Arabic/layout pipeline eventually produces the glyph sequences a legacy renderer should display.

A game engine still needs its own binary representation.

The Text Codec Core provides the boundary:

```text
engine bytes
   ↕
GameTextCodec
   ↕
TokenStream
```

## Why a project-specific codec contract

Python's codec infrastructure supports custom codecs and even arbitrary transforms, but several convenience APIs are specifically constrained to str/bytes iteration. Classic Retro needs a structured TokenStream containing visible text, runtime variables, control operations, page boundaries, and lossless opaque bytes.

Reference:

- https://docs.python.org/3/library/codecs.html

Construct provides a strong declarative, symmetrical parse/build model for binary structures, and Kaitai Struct provides portable declarative binary-format descriptions.

References:

- https://construct.readthedocs.io/en/latest/intro.html
- https://kaitai.io/
- https://formats.kaitai.io/

Those tools remain valid choices inside future platform/engine adapters for archives, executables, headers, or complex resources.

The core text codec itself stays dependency-free because its semantics are TokenStream-specific and small enough to define explicitly.

## GameTextCodec contract

Every codec must provide:

```text
decode(bytes) -> DecodedMessage
encode(TokenStream) -> bytes
verify_round_trip(bytes)
```

DecodedMessage records:

- decoded TokenStream,
- number of source bytes consumed,
- the terminator ID when a configured terminator ended the message.

This lets extractors decode one message out of a larger script bank without assuming the whole remaining buffer belongs to that message.

## Safe fixed-table codec

TableTextCodec handles engines whose glyphs and protected operations have fixed byte sequences.

A JSON profile can define:

- glyph Unicode sequence -> bytes,
- fixed variable/control/break token -> bytes,
- one or more terminators,
- strict or opaque handling for unknown bytes.

Example:

```json
{
  "schema_version": "1.0",
  "id": "example",
  "glyphs": [
    {"sequence": "A", "bytes_hex": "41"},
    {"sequence": "B", "bytes_hex": "42"}
  ],
  "inline_codes": [
    {
      "type": "control",
      "movement": "ordered",
      "name": "WAIT",
      "args": {"frames": 30},
      "bytes_hex": "F0 02"
    }
  ],
  "terminators": [
    {"id": "end", "bytes_hex": "FF"}
  ]
}
```

## Prefix-free binary tables

The generic fixed-table codec deliberately requires every configured binary code to be prefix-free across glyphs, fixed inline codes, and terminators.

For example, these are rejected:

```text
A = 01
B = 01 02
```

Without engine-specific state, byte stream 01 02 could mean either B or A followed by another code. The generic core refuses to guess.

An actual game format that intentionally uses prefix opcodes, parameter lengths, stateful encodings, escape bytes, or context-dependent decoding should implement a dedicated GameTextCodec in its Engine Adapter.

This keeps the generic codec safe instead of making it appear more universal than it is.

## Unicode sequences

Encoding uses longest-match over Unicode glyph sequences.

That permits an engine/font to define a multi-code-point glyph or ligature while still keeping the underlying translation Unicode-based.

Binary decoding remains unambiguous because the configured byte codes are prefix-free.

## Fixed versus parameterized controls

TableTextCodec can represent a fixed instruction including fixed arguments:

```text
WAIT(frames=30) -> F0 02
```

It will not silently encode:

```text
WAIT(frames=60)
```

unless that exact semantic token has its own configured code.

Engines where an opcode is followed by parameter bytes need a dedicated codec implementation. The abstract GameTextCodec contract exists specifically for that case.

## Unknown bytes and reverse engineering

Two policies exist.

### error

Default for supported builds.

An unknown byte raises UNKNOWN_TEXT_BYTE. This prevents incomplete mappings from silently corrupting text.

### opaque

Opt-in research mode.

Consecutive unknown bytes become an ordered OPAQUE token containing their exact hexadecimal data. Encoding that token writes the original bytes unchanged.

This allows exploratory extraction and exact round trips while an opcode or glyph is still being reverse engineered.

Opaque mode does not mean the unknown bytes are safe to move or translate.

## Round-trip verification

Before a codec is trusted for a game resource:

```text
original bytes
  -> decode
  -> encode without edits
  -> byte-for-byte compare
```

A mismatch raises TEXT_CODEC_ROUNDTRIP_FAILED.

The comparison covers exactly the bytes consumed by the decoded message, including its terminator when present.

This is a required building block for the project's later extraction/rebuild acceptance tests.

## Terminators

Terminators are semantic IDs backed by exact bytes.

A codec may have multiple terminators if the engine distinguishes different message endings.

The caller can require a terminator. Unexpected end-of-buffer then fails with MISSING_TERMINATOR rather than treating truncated text as valid.

## CLI

```text
classic-retro codec verify profile.json text-fixture.bin --require-terminator
```

The command loads the profile, decodes one message, rebuilds it, and succeeds only when the consumed bytes are identical.

## Scope boundary

This layer does not find text in a ROM, relocate expanded data, repair pointers, decompress script archives, or decide which Arabic pipeline output a renderer needs.

Those responsibilities belong to Engine/Game Adapters and the later extraction/rebuild layers.
