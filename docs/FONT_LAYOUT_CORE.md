# Font, Glyph, and Text Layout Core

Version: 1

## Purpose

Retro games do not share a universal font renderer. A font may be fixed-width, variable-width, tile-based, sprite-based, software-rendered, or stored in a custom archive.

Classic Retro therefore keeps the generic layout core independent from binary font storage.

Engine adapters provide a FontProfile containing the glyphs and metrics that their renderer can actually draw.

## Font profile

A glyph has:

- stable id,
- Unicode sequence,
- pixel advance,
- optional ink width/height,
- optional x/y offset.

A glyph sequence can contain one or more Unicode code points.

The resolver uses longest-sequence matching. This supports both ordinary one-code-point glyphs and engine-defined multi-code-point glyphs or ligatures without changing the layout algorithm.

Unknown glyphs fail with MISSING_GLYPH. There is deliberately no silent fallback glyph in the core.

## Pixel width

Line width is based on glyph advance in pixels, never Unicode character count, terminal cell width, or byte length.

Runtime inline variables also participate in width measurement.

For example, PLAYER may be replaced with a name at runtime. The engine must supply a safe maximum advance for that variable. If no width is declared, layout fails with INLINE_WIDTH_UNKNOWN instead of guessing.

Control codes and opaque non-rendering commands have zero advance by default.

## Arabic and line breaking order

Unicode UAX #9 states that glyph shaping is used to calculate widths, line wrapping is determined from those widths, and display reordering is then applied per line.

It also states that line-breaking width calculations for cursively connected scripts must use shaped glyphs.

References:

- https://www.unicode.org/reports/tr9/
- https://www.unicode.org/reports/tr14/

Classic Retro follows the same design principle.

For each candidate logical line:

1. keep logical TokenStream order,
2. normalize and shape Arabic,
3. apply bidi reordering for that line,
4. map the resulting visual sequences to real game glyphs,
5. sum pixel advances,
6. accept the candidate only if it fits the box.

Because final shaping is executed for each chosen line, Arabic joining at line boundaries is recalculated rather than reusing a visual-order paragraph that was shaped before wrapping.

## Unicode line-break opportunities

UAX #14 defines legal break opportunities but deliberately leaves the final width-based choice to higher-level layout software.

The default BreakProvider uses uniseg 0.10.1:

- pure Python,
- portable across the project's supported operating systems,
- Python 3.9+,
- its 0.9+ implementation passes the complete Unicode breaking tests for its supported Unicode data.

References:

- https://pypi.org/project/uniseg/
- https://uniseg-py.readthedocs.io/en/stable/linebreak.html
- https://uniseg-py.readthedocs.io/en/stable/wrap.html

### Unicode-version caveat

The current uniseg 0.10.1 data implements Unicode 16.0 line breaking, while the current Unicode Standard is 18.0.

Unicode 18 changed several UAX #14 details, including properties/rules around FIGURE DASH, EN DASH, SOFT HYPHEN, and BA followed by GL.

Reference:

- https://www.unicode.org/reports/tr14/

Classic Retro does not claim Unicode 18 line-break conformance through uniseg 0.10.1.

The dependency is isolated behind BreakProvider so it can be upgraded or replaced without changing font measurement or layout APIs. Engine adapters may also provide tailored break behavior where a game's renderer has stricter rules.

## Inline objects

UAX #14 assigns U+FFFC OBJECT REPLACEMENT CHARACTER to the contingent-break class and explicitly notes that object-specific behavior may override breaks before/after the object.

Classic Retro uses a U+FFFC shadow character only while calculating break opportunities.

Each runtime object then supplies its own policy:

- variable: break before/after by default once a maximum width is defined,
- control code: no break around it by default,
- opaque command: no break around it by default,
- line break: mandatory line boundary,
- page break: mandatory page boundary.

The shadow character never reaches the game or translation file.

Reference:

- https://www.unicode.org/reports/tr14/

## Explicit line and page breaks

LINE_BREAK starts another line in the same page.

PAGE_BREAK finishes the current page and resets the max-lines counter for the next page.

This lets game adapters represent real dialogue-box behavior rather than treating page breaks as ordinary whitespace.

## Overflow behavior

The core fails closed.

TEXT_OVERFLOW means one unbreakable unit cannot fit within the pixel width.

TEXT_BOX_OVERFLOW means the page requires more lines than the box allows.

Automatic font shrinking or arbitrary mid-word breaks are not performed. An engine adapter can later opt into a documented alternative policy if the original game supports one.

## Current boundary

This layer describes glyph identity and layout metrics only.

Building a game's Arabic font uses other shared modules:

- `font.glyph_raster` draws each form from the TTF into the game's cell.
- `font.tiles` stores pixels as 4bpp tiles.
- `arabic.glyph_codes` gives each form its character codes.

Writing a ROM font in the game's own format stays with each engine (see [ARABIC_STRATEGIES.md](ARABIC_STRATEGIES.md#the-shared-core)).
