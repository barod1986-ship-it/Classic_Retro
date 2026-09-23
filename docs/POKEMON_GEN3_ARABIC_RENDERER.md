# Pokémon Gen III Arabic Renderer / Font v1

## Design

FireRed's upstream gbagfx tool already converts font PNG assets into the game's font format. Classic Retro reuses that path rather than introducing another binary font container.

The original renderer treats F9 xx as CHAR_EXTRA_SYMBOL and promotes xx to glyph ID 0x100 | xx. GetStringWidth uses the same mechanism. Arabic therefore uses a reserved part of this secondary glyph page instead of deleting Latin glyphs.

Reserved v1 range:

- extra-symbol byte: 0x40 and above
- rendered glyph ID: 0x140 and above
- existing upstream extra symbols remain below this range

## Shaping, bidi, and paint order

Translations remain logical Unicode Arabic.

Classic Retro:

1. rejects combining harakat in this first engine profile instead of silently dropping them,
2. applies the shared Arabic shaper with ligatures disabled,
3. applies Unicode bidi to each movable text segment,
4. converts that visual result into the order needed by a renderer that paints from the right edge toward the left,
5. maps Arabic presentation glyphs to F9 xx,
6. keeps ordered game control codes in execution order.

The final paint-order conversion is performed after bidi processing. It is not a naive reversal of the translator's logical Arabic input.

## Runtime RTL controls

The source overlay adds two engine controls:

- FC 19 xx: enable RTL and set the line right edge to text-box x + xx
- FC 1A: return to LTR

While RTL is enabled, the renderer subtracts the glyph advance before drawing. Newline, clear, and scroll states restore the configured right edge.

RTL state is stored per TextPrinter, not globally.

## Font atlas

The prepare-arabic-source command accepts a user-supplied Arabic-capable TTF or OTF. Classic Retro does not distribute a third-party font file.

The compiler:

- chooses the largest size that fits the FireRed 16x16 Arabic glyph cell,
- uses one baseline across contextual forms,
- rasterizes background / foreground / shadow semantic pixels,
- writes graphics/fonts/arabic_normal.png,
- writes a one-byte-per-glyph width table,
- patches graphics_file_rules.mk so upstream gbagfx creates arabic_normal.hwlatfont.

## Exact upstream pinning

The overlay targets only pret/pokefirered commit c75f352304d529f6ba92d4f74b9cf8b5c3810788.

Before modification, Classic Retro calculates Git blob SHA-1 values for every upstream file it touches and refuses a mismatch.

CI checks out that exact upstream commit and runs the overlay as a dry-run. Source drift therefore becomes an explicit failure.

## Commands

Check the pinned source:

    classic-retro pokemon-gen3 source-check /path/to/pokefirered

Apply RTL/font support:

    classic-retro pokemon-gen3 prepare-arabic-source /path/to/pokefirered --font /path/to/ArabicFont.ttf

Inspect bytes produced for a logical Arabic line:

    classic-retro pokemon-gen3 encode-arabic "مرحبا 123" --right-x 220

Then build FireRed Rev 1 using the pinned upstream build target firered_rev1.

## v1 boundary

- Arabic dialogue currently uses one shared Arabic glyph style even when the current game font is small, male, or female.
- Combining harakat are rejected.
- Arabic ligatures are disabled.
- The RTL source engine and font path are established; bulk translation import into upstream dialogue sources is a later step.
