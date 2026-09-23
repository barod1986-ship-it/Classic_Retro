# Extraction / Rebuild Core

Version: 1

## Purpose

A translation can become larger than the original encoded text. Classic Retro therefore needs to treat text as a binary resource with explicit references and explicit safe relocation regions.

The core model is:

```text
original image
  ↓
declared resource ranges
  ↓
extract
  ↓
edit / re-encode
  ↓
place in original range or verified safe region
  ↓
rewrite declared references
  ↓
validate
  ↓
rebuilt image
```

## Research basis

Retro script tools already demonstrate why pointer handling must be flexible.

Cartographer documents absolute pointers, relative pointers, PC-relative pointers, configurable pointer sizes, endianness, spacing, and base values.

Atlas supports embedded pointers, pointer tables, pointer lists, and multiple pointer-calculation methods.

References:

- https://github.com/Normmatt/Densetsu-no-Stafy-GBA-Translation/blob/master/cartographer/Cartographer-readme.txt
- https://github.com/stevemonaco/Atlas

Modern ROM-hacking tools such as RTHextion also expose multiple pointer types and platform-specific pointer arithmetic rather than assuming one universal pointer format.

Reference:

- https://github.com/road-t/RTHextion

## References

The generic IntegerReferenceCodec uses an affine model:

```text
target_offset = base(site) + stored_value * scale + addend
```

Encoding uses the inverse operation and fails if the target is not exactly representable.

Base modes:

- zero
- constant
- reference-site-relative

This covers many common absolute, relative, and PC-relative integer references.

A platform-specific mapping that is not affine, such as some banked address formats, must implement its own reference codec in the relevant adapter rather than forcing the generic model to guess.

The codec also checks integer width and signedness.

## Resource ranges

Resource ranges are half-open byte intervals:

```text
[start, end)
```

The plan rejects overlapping source resources and overlapping reference sites.

References are verified against the original image before any write. If a pointer declared as targeting resource A does not decode to A's original start, rebuilding stops with REFERENCE_TARGET_MISMATCH.

This catches wrong revisions, stale research notes, and incorrect pointer assumptions before data is modified.

## Safe regions

The core never discovers free space by scanning for long runs of 00 or FF.

A Game/Engine Adapter must explicitly declare safe regions based on verified knowledge of that exact game revision.

This is deliberate: apparently empty regions can still be referenced or have runtime meaning. A recent GBA binary-hacking project explicitly notes that it verifies expansion space with pointer scanning because live pointers can point into areas that look empty.

Reference:

- https://github.com/Nn-Exe/Pokemon-Hyper-Emerald-5.7-QoL

A safe region may optionally specify an expected fill byte. This is only a sanity check that the user's exact input still looks as expected; a fill pattern by itself is never treated as proof that a region is safe.

Safe regions are forbidden from overlapping declared source resources or reference fields.

## Allocation

Relocated resources use deterministic best-fit allocation:

1. inspect only declared safe regions,
2. respect the resource alignment,
3. select the fitting gap with the least unused capacity,
4. break ties by lowest address and region id,
5. split the remaining gap.

The allocator does not expand the file implicitly.

If a platform supports safe ROM expansion, that must be introduced through a separate explicit image-expansion policy with platform limits and checksum rules.

## In-place writes

A resource stays at its original address when:

- allow_in_place is true, and
- its rebuilt payload fits inside the original range.

Only the rebuilt payload bytes are overwritten. The unused suffix of a shorter original allocation is left untouched.

This avoids inventing a padding policy that may be wrong for a particular engine.

If an engine requires cleared padding, that behavior belongs in its adapter/build hook.

## Relocation

When a payload no longer fits:

1. allocate a verified safe region,
2. write the new payload,
3. update all declared references,
4. leave the old bytes untouched.

Leaving old data intact is intentionally conservative. The generic core cannot know whether an undeclared secondary reference still exists.

An adapter can later perform explicit cleanup once all ownership is proven.

## Write collision safety

Every binary write is recorded.

Overlapping writes fail with OVERLAPPING_WRITE rather than relying on write order.

The generic plan also forbids reference fields from living inside declared resource ranges. Embedded/self-relocating references require a dedicated engine rebuild implementation because moving the containing resource also moves the reference site.

## Round-trip gate

Before translated data is trusted:

```text
extract original resource bytes
  ↓
rebuild without edits
  ↓
compare entire image byte-for-byte
```

Any difference raises REBUILD_ROUNDTRIP_FAILED.

This is stronger than merely checking that extracted text can be re-encoded. It verifies resource placement and all declared references together.

## CLI / future adapters

The data model is versioned through:

```text
rebuild-plan.schema.json
```

A plan can be checked against an image with:

```text
classic-retro rebuild verify plan.json game.bin
```

The command extracts every declared original resource and rebuilds the image without edits. Success means the entire image is byte-identical.

Engine/Game Adapters can construct RebuildPlan objects directly or load versioned plan data.

The current core intentionally stops before ROM expansion, compression, pointer discovery, and automatic reference tracing. Those behaviors require platform/engine-specific evidence.
