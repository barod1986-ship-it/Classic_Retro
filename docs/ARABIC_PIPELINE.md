# Arabic Core Pipeline

Version: 1

## Purpose

Classic Retro stores Arabic translation in logical Unicode order and prepares it for different classes of game renderer.

A target's translations file (`translations/<target>.json`) holds logical Arabic, never shaped or reversed visual text.

## Standards basis

Unicode 18.0 specifies bidirectional layout in UAX #9 and normalization in UAX #15.

References:

- https://www.unicode.org/reports/tr9/
- https://www.unicode.org/reports/tr15/
- https://www.unicode.org/versions/Unicode18.0.0/core-spec/chapter-9/
- https://www.unicode.org/reports/tr53/

Unicode recommends NFC as the normal form for general text. NFKC/NFKD are intentionally not used for ordinary translation text because compatibility normalization can erase distinctions needed for round-trip or legacy mappings.

## Pipeline outputs

One logical target TokenStream produces three representations.

### normalized

Logical-order Unicode text normalized to NFC.

Use this for renderers that already implement Arabic shaping and bidi layout.

### shaped

Logical-order text where Arabic letters have been converted to contextual presentation forms.

Use this only when an engine can handle RTL ordering but cannot shape Arabic glyphs itself.

### visual

Shaped text reordered for visual display with RTL base direction.

Use this for legacy renderers that draw glyphs from left to right and provide neither Arabic shaping nor bidi layout.

These stages must not be stacked blindly. Passing the visual output into a modern HarfBuzz/Raqm-style renderer would perform shaping/bidi twice and corrupt text.

Arabic Reshaper documents that bidi reordering is optional and depends on the capabilities of the destination renderer:

- https://github.com/mpcabd/python-arabic-reshaper

## Dependencies

### arabic-reshaper 3.x

Used for legacy contextual Arabic shaping.

The project is MIT licensed, supports Python 3.10+, and version 3.0.1 modernized packaging and test coverage.

- https://pypi.org/project/arabic-reshaper/
- https://github.com/mpcabd/python-arabic-reshaper

Default Classic Retro policy:

- preserve harakat,
- preserve tatweel,
- support ZWJ,
- disable ligatures.

Ligatures are disabled because a retro game font may not contain the resulting ligature glyph. Engine/font adapters can later opt in when their glyph set proves support.

### python-bidi 0.6.11

Used for Unicode bidirectional display ordering.

The current package wraps the Rust unicode-bidi implementation, supports Python 3.9 through 3.14, and exposes get_display with an explicit base direction.

- https://pypi.org/project/python-bidi/
- https://github.com/MeirKriheli/python-bidi

Classic Retro uses RTL paragraph direction by default because the target language is Arabic. AUTO and LTR remain available as explicit configuration choices for special engine resources.

## Protected token strategy

The bidi algorithm must see control codes and runtime variables as inline objects without turning them into ordinary visible text.

UAX #9 states that inline objects are treated like U+FFFC OBJECT REPLACEMENT CHARACTER.

Classic Retro therefore temporarily replaces each protected token with a unique, bidi-neutral marker built from U+FFFC and Control Pictures whose bidi class is Other Neutral.

The marker is a palindrome:

```text
FFFC + A + B + A + FFFC
```

This matters because visual reordering may reverse a run. A palindrome remains byte-for-byte recognizable after reversal.

The marker is never stored in translation files and is restored immediately after shaping/bidi processing.

With 39 stable Control Picture symbols used as A/B values, one message can contain up to 1521 protected inline tokens.

## Input rules

Logical translation text rejects:

- Arabic Presentation Forms blocks,
- explicit bidi embedding/override/isolate formatting controls,
- U+FFFC, which is reserved internally.

Arabic Presentation Forms are output artifacts for legacy rendering, not canonical translator input.

Explicit bidi controls are rejected because they introduce hidden directional state. Mixed Arabic, Latin text, punctuation, and numbers should normally be resolved by the Unicode Bidirectional Algorithm and the configured base direction.

## Harakat

Harakat are preserved by default. They are not silently deleted.

No target's font places marks yet, so every target refuses a line that holds one instead of losing it (`arabic.paint.reject_combining_marks`; `arabic.logical.check_logical_arabic` for the targets that draw whole lines). Whether each form has a glyph and each line fits its box is the target's own check.

UAX #53 describes Arabic combining-mark rendering as a rendering-stage process rather than a new normalization form.

## How the targets use it

- `arabic.logical` holds what logical text may contain: a translations file refuses direction controls, and an engine refuses presentation forms and characters its font cannot draw.
- `arabic.repertoire.legacy_renderer_pipeline()` is the configuration every glyph target shapes with (no ligatures, nothing dropped), and `arabic_presentation_repertoire()` lists every form it can produce.
- `arabic.paint` turns the visual output into the order a right-to-left renderer paints, and refuses marks and mirrored brackets a game font cannot draw.
- `arabic.glyph_codes` gives the forms a script uses their codes in the game's font.

```text
classic-retro targets check-translations TARGET [--font FONT --preview-dir DIR]
```

This runs a target's whole script through the pipeline and its engine: the logical-text checks, shaping, paint order and the original's commands; with a font, it also draws every form and measures every line against its box.
