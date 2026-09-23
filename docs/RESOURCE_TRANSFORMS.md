# Compression / Resource Transform Core

Version: 1

## Purpose

Classic games use many different resource encodings.

A resource may be raw, compressed, filtered, encrypted, packed, or transformed through several stages. The same console can use more than one compression family, and individual games often add custom formats.

For example, GBA BIOS decompression services include LZ77, Huffman, run-length, bit-unpack, and differential filters.

References:

- https://gbadev.net/tonc/bitmaps.html
- https://gbadev.net/libtonc/group__grpBiosMain.htm

Classic Retro therefore models compression as a composable ResourceTransform rather than attaching one universal compressor to a platform.

## Contract

Every transform implements:

```text
decode(encoded bytes) -> decoded payload + metadata
encode(decoded payload, metadata) -> encoded bytes
```

A TransformPipeline runs decode stages in declaration order and encode stages in reverse order.

This also supports non-compression transforms later, such as byte filters or game-specific wrappers.

## Exact unchanged rebuilds

Recompression is not guaranteed to reproduce the original compressed byte stream.

Two valid encoders can create different compressed streams that decode to the same payload. Encoder settings and library versions can also affect output.

Classic Retro therefore stores a TransformSnapshot during extraction.

If the decoded payload is unchanged, rebuilding returns the original encoded bytes verbatim.

This guarantees:

```text
extract unchanged resource
  -> rebuild
  -> exact original packed bytes
```

without requiring the project's compressor to imitate the original game's compressor byte-for-byte.

If the decoded payload changes, the configured encoder is used and the new encoded stream is immediately decoded again. A mismatch fails with TRANSFORM_ROUNDTRIP_FAILED.

## Built-in transforms

The core includes conservative standard-library transforms:

- identity
- zlib
- raw-deflate
- gzip

Python's zlib API exposes compression level, window bits, raw DEFLATE, zlib wrappers, and gzip wrappers.

Reference:

- https://docs.python.org/3/library/zlib.html

Python 3.14 gzip output defaults to mtime=0 for reproducible output. Classic Retro uses the zlib gzip wrapper directly, which avoids embedding a current timestamp.

Reference:

- https://docs.python.org/3/library/gzip.html

Exact compressed-byte reproducibility across different zlib library versions is not promised. Exact unchanged rebuilds come from snapshot reuse instead.

## Safety limits

Built-in DEFLATE-family transforms default to a 64 MiB maximum decoded size.

The limit is configurable per transform profile.

The decoder also requires:

- a complete compressed stream,
- no trailing bytes outside that stream.

This prevents a loosely specified resource range from silently swallowing unrelated data.

A game format that intentionally concatenates members or includes a wrapper/trailer should use a dedicated transform.

## Custom engine transforms

External transforms can register through the versioned entry-point group:

```text
classic_retro.transforms.v1
```

A builder receives profile options and returns a ResourceTransform.

This is where platform/engine support should add formats such as:

- GBA BIOS LZ77/RLE/Huffman,
- game-specific LZSS,
- custom dictionary compression,
- archive wrappers,
- differential filters.

The generic core does not pretend those formats are interchangeable.

## Transform profiles

Pipelines are versioned JSON documents:

```json
{
  "schema_version": "1.0",
  "id": "dialogue",
  "stages": [
    {
      "codec": "zlib",
      "options": {
        "level": 9,
        "max_output_bytes": 1048576
      }
    }
  ]
}
```

Schema:

```text
transform-pipeline.schema.json
```

## Rebuild integration

The transformed rebuild layer sits on top of the existing resource relocation core.

Flow:

```text
packed resource range
  -> transform pipeline decode
  -> editable payload
  -> transform pipeline rebuild
  -> packed payload
  -> in-place write or safe-region relocation
  -> pointer/reference update
```

If an unchanged transformed resource is rebuilt, its original packed bytes are reused and the entire image remains byte-identical.

If a translated payload compresses larger than the original resource range, the existing safe-region allocator can relocate the newly packed resource and update declared references.

## Current boundary

The transform core does not auto-detect compression.

Compression detection must come from exact game/engine research or a format signature with strong evidence.

It also does not yet implement console-specific compressors. Those belong to platform/engine adapters with known fixtures and round-trip tests.
