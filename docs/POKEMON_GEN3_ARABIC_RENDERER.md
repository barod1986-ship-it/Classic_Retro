# Pokémon Gen III Arabic Renderer / Font v1

## Design

FireRed's upstream gbagfx tool already converts 16x16 font PNG cells into the game's full-width Latin font format. Classic Retro reuses that path rather than introducing another binary font container.

The original renderer treats F9 xx as CHAR_EXTRA_SYMBOL and promotes xx to glyph ID 0x100 | xx. GetStringWidth uses the same mechanism. Arabic therefore uses a reserved part of this secondary glyph page instead of deleting Latin glyphs.

The pinned FireRed charmap already uses F9 00..17 and F9 D0..FE. Its only contiguous free span is F9 18..CF. Arabic v1 deliberately uses a subset beginning at F9 40, leaving F9 18..3F free for future engine symbols.

Reserved Arabic v1 range:

- extra-symbol bytes: F9 40..CF maximum
- rendered glyph IDs: 0x140..0x1CF maximum
- source-overlay validation rejects any collision with an upstream F9 assignment

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

The source overlay adds three engine controls:

- FC 19 xx: enable RTL and set the line right edge to text-box x + xx
- FC 1A: return to LTR
- FC 1B pp: expand placeholder pp as an isolated LTR run before RTL rendering

FC 1B is consumed by FireRed's StringExpandPlaceholders path. PLAYER/RIVAL names are
expanded, reversed by glyph units (not raw bytes), and then painted by the RTL
renderer. This is the engine-level equivalent of keeping a dynamic Latin name
isolated from the surrounding Arabic run.

While RTL is enabled, the renderer subtracts the glyph advance before drawing. Newline, clear, and scroll states restore the configured right edge.

RTL state is stored per TextPrinter, not globally.

## Font atlas

The prepare-arabic-source command accepts a user-supplied Arabic-capable TTF or OTF. Classic Retro does not distribute a third-party font file.

The compiler:

- chooses the largest size that fits FireRed's actual 16x14 copied glyph region,
- rasterizes logical letters plus joining context through HarfBuzz and FreeType,
- rejects fonts that substitute missing-letter rectangles,
- uses one baseline across contextual forms,
- left-aligns every glyph at x=0 because CopyGlyphToWindow copies only columns 0..glyphWidth,
- derives glyph width from the font's real advance instead of the centered ink span,
- keeps foreground and shadow pixels inside the declared copied width,
- writes the atlas as native 2bpp palette PNG,
- rasterizes background / foreground / shadow semantic pixels,
- writes graphics/fonts/arabic_normal.png,
- writes a one-byte-per-glyph width table,
- patches graphics_file_rules.mk so upstream gbagfx creates arabic_normal.fwlatfont.

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

## Dynamic PLAYER / RIVAL names

The full Professor OAK reference speech uses FC 1B for PLAYER and RIVAL. The
upstream StringExpandPlaceholders routine expands the selected Latin name, and
Classic Retro reverses it by encoded glyph units before the already-RTL printer
paints it from right to left. This keeps a name such as RED visually RED rather
than DER.

The name-entry UI itself is still the original FireRed Latin input UI. Supporting
Arabic name entry is a separate feature from displaying dynamic Latin names
correctly inside Arabic dialogue.

## v1 boundary

- Arabic dialogue currently uses one shared Arabic glyph style even when the current game font is small, male, or female.
- Combining harakat are rejected.
- Arabic ligatures are disabled.
- All 13 Professor OAK speech strings in the new-game intro are the end-to-end reference translation.
- Wider game dialogue import and Arabic name-entry UI remain later steps.

## Reference font

The CI reference build uses **Noto Kufi Arabic SemiBold** from the Noto Arabic
family. Noto Arabic is licensed under the SIL Open Font License 1.1.

The actual font size is measured from the contextual outlines; it is not assumed
from the font family name. The build report records the resulting size and the
resolved font identity so that visual results can be reproduced and compared.

The toolkit still accepts another Arabic-capable TTF/OTF through `--font`.
The glyph-bound validator rejects a font/rasterization combination if any visible
pixel would be outside the width or height that FireRed actually copies.

### OpenType font correction

The earlier atlas generator requested Unicode Presentation Forms directly from
the font. Noto Kufi Arabic has logical-letter mappings and OpenType substitutions,
but can lack those Presentation Forms mappings. It therefore returned nonempty
missing-glyph rectangles, which passed the old ink-bounds tests. The earlier claim
of a readable 13px reference font was based on those rectangles and was incorrect.

The generator now converts each presentation form to its logical letter with
zero-width joining context and lets HarfBuzz select the contextual outline. An in-memory cmap maps the game
slot identifiers to those glyphs; Pillow then rasterizes them without a second
shaping pass. The original font file is never modified.
Presentation forms remain the game's slot identifiers. Actual font size is chosen
from these real outlines and recorded, with the font SHA-256, in `build-report.json`.
The artifact also includes the atlas and the resolved font family/style for review.
The `uharfbuzz` and `fonttools` dependencies make this work on Windows as well
as Linux without requiring Pillow's optional libraqm component. Fonts requiring
multi-glyph/offset placement for one contextual character are rejected in v1.
Joining forms trim blank edge pixels so neighbouring glyph cells touch.
The reference font file is pinned by commit and SHA-256; fontconfig no longer
substitutes Regular for the requested SemiBold weight.

### Source preparation and renderer regressions

Font generation completes before any upstream source edit. A successful preparation
records the overlay version and touched-source hashes in `.classic-retro-arabic.json`.
Reusing a modified or old/untracked overlay is rejected; start with a fresh checkout
of the pinned commit to upgrade. A valid existing overlay can regenerate its font.

Newline, page-clear, and scroll all restore the RTL right edge. The separate LTR
control restores the left edge. Dynamic names are reversed along forward-parsed
glyph boundaries, including extra-symbol arguments that equal F8/F9/FF.
Regression tests execute these C helpers and build a synthetic OpenType font that
has contextual substitutions without Presentation Forms mappings.
