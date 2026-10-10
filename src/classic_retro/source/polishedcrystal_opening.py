"""First Arabic dialogue proof for Polished Crystal v3.2.3 RGBDS source.

Composes connected RTL lines into eight-pixel cells for professor Elm's
first speech. This is not yet a general dynamic Arabic renderer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

from classic_retro.core.errors import ClassicRetroError, ErrorCode
from classic_retro.source.polishedcrystal_catalog import _verify_upstream

COLUMNS = 18
CELL_SIZE = 8
FONT_TILES = 114
FIRST_ARABIC_CODE = 0x80
LAST_ARABIC_CODE = 0xD7  # preserve high glyphs, including the prompt arrow
OUTPUT_FONT = "gfx/font/classic_retro_arabic_elm.1bpp"
MARKER = "ClassicRetroArabicElmFont"
OPENING_LINES = (
    ("text", "أهلًا بك!"),
    ("line", "آسف لأنني تأخرت!"),
    ("para", "مرحبًا بك في"),
    ("line", "عالم البوكيمون!"),
    ("para", "اسمي إلم."),
    ("para", "يسمونني أستاذ"),
    ("line", "البوكيمون!"),
)
SOURCE_FILES = {
    "data/text/common.asm": "d76b34846468a29aa36ff83795a1ecb87330cfb7",
    "engine/menus/intro_menu.asm": "e8aaa31bfb414c71c4250b2035b26bd2c1a566ac",
}


@dataclass(frozen=True)
class ElmArabicAssets:
    tiles: bytes
    codes: tuple[tuple[int, ...], ...]
    images: tuple[Image.Image, ...]
    used_glyphs: int


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _raster_line(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Return one fully shaped RTL line in an 18-cell-wide monochrome image."""
    bbox = font.getbbox(text, direction="rtl")
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if not 0 < width <= COLUMNS * CELL_SIZE - 4 or height < 1:
        raise ClassicRetroError(
            ErrorCode.TEXT_OVERFLOW, f"Elm Arabic line is {width}px (max 140): {text!r}"
        )
    native = Image.new("L", (width + 2, height + 2))
    ImageDraw.Draw(native).text(
        (1 - bbox[0], 1 - bbox[1]), text, font=font, direction="rtl", fill=255
    )
    compressed = native.resize((width + 2, 7), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (COLUMNS * CELL_SIZE, CELL_SIZE))
    canvas.paste(compressed, (COLUMNS * CELL_SIZE - width - 4, 0))
    return canvas.point(lambda pixel: 255 if pixel >= 120 else 0).convert("1")


def _tile_bytes(image: Image.Image, column: int) -> bytes:
    pixels = image.load()
    return bytes(
        sum((1 << (7 - x)) for x in range(8) if pixels[column * CELL_SIZE + x, y]) for y in range(8)
    )


def make_assets(source: Path, font_path: Path) -> ElmArabicAssets:
    """Start with the game's own normal font so untranslated glyphs survive."""
    if not features.check("raqm"):
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED, "Pillow needs RAQM for Arabic shaping/RTL"
        )
    normal = source / "gfx/font/normal.1bpp"
    if not normal.is_file() or normal.stat().st_size != FONT_TILES * CELL_SIZE:
        raise ClassicRetroError(
            ErrorCode.FONT_BUILD_FAILED,
            "build pristine Polished Crystal first (make crystal) to generate normal.1bpp",
        )
    if not font_path.is_file():
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, f"Font not found: {font_path}")
    try:
        font = ImageFont.truetype(str(font_path), 13, layout_engine=ImageFont.Layout.RAQM)
        if font.getmask("م", direction="rtl").getbbox() is None:
            raise ValueError("Arabic glyph missing")
        images = tuple(_raster_line(line, font) for _, line in OPENING_LINES)
    except (ValueError, OSError) as exc:
        raise ClassicRetroError(ErrorCode.FONT_BUILD_FAILED, str(exc)) from exc
    atlas = bytearray(normal.read_bytes())
    mapping: dict[bytes, int] = {}
    lines: list[tuple[int, ...]] = []
    for image in images:
        row = []
        for column in range(COLUMNS):
            tile = _tile_bytes(image, column)
            if tile == bytes(CELL_SIZE):
                row.append(0x7F)
                continue
            if tile not in mapping:
                code = FIRST_ARABIC_CODE + len(mapping)
                if code > LAST_ARABIC_CODE:
                    raise ClassicRetroError(
                        ErrorCode.ARABIC_GLYPH_CAPACITY_EXCEEDED,
                        f"Elm opening needs {len(mapping) + 1} glyphs",
                    )
                mapping[tile] = code
                offset = (code - FIRST_ARABIC_CODE) * CELL_SIZE
                atlas[offset : offset + CELL_SIZE] = tile
            row.append(mapping[tile])
        lines.append(tuple(row))
    return ElmArabicAssets(bytes(atlas), tuple(lines), images, len(mapping))


def _opening_asm(codes: tuple[tuple[int, ...], ...]) -> str:
    asm = ['SECTION "_ElmText1", ROMX', "_ElmText1::", "\ttext_start"]
    for index, ((directive, _), line) in enumerate(zip(OPENING_LINES, codes, strict=True)):
        if index == 2:
            asm += ["", "if !DEF(DEBUG)"]
        if directive != "text":
            control = {"line": "<LINE>", "para": "<PARA>"}[directive]
            asm.append('\tdb "' + control + '"')
        # Raw bytes avoid the game's original English-only Huffman tree.
        asm.append("\tdb " + ", ".join("$" + format(byte, "02x") for byte in line))
    asm += ["endc", '\tdb "<PROMPT>"', "", ""]
    return "\n".join(asm)


def _replace_once(original: str, before: str, after: str, label: str) -> str:
    if original.count(before) != 1:
        raise ClassicRetroError(
            ErrorCode.SOURCE_BASELINE_MISMATCH, f"{label} lacks its unique original anchor"
        )
    return original.replace(before, after)


def _source_overlays(source: Path, asset: ElmArabicAssets) -> dict[Path, bytes]:
    common = source / "data/text/common.asm"
    intro = source / "engine/menus/intro_menu.asm"
    original_common = common.read_text(encoding="utf-8")
    start = 'SECTION "_ElmText1", ROMX\n'
    end = 'SECTION "_ElmText2", ROMX\n'
    if original_common.count(start) != 1 or original_common.count(end) != 1:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "intro labels changed")
    prefix, middle = original_common.split(start, 1)
    old_scene, tail = middle.split(end, 1)
    if "_ElmText1::" not in old_scene or "prompt" not in old_scene:
        raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, "opening text changed")
    new_common = (
        prefix
        + _opening_asm(asset.codes)
        + end
        + tail
        + '\nSECTION "Classic Retro Arabic Elm Font", ROMX\n'
        + f'{MARKER}::\n\tINCBIN "{OUTPUT_FONT}"\n'
    )
    original_intro = intro.read_text(encoding="utf-8")
    old_call = "\tld hl, ElmText1\n\tcall PrintText\n"
    new_call = "\tld hl, ElmText1\n\tfarcall ClassicRetroPrintArabicElm\n"
    new_intro = _replace_once(original_intro, old_call, new_call, "Elm call")
    routine = (
        "ClassicRetroPrintArabicElm::\n"
        "\tpush hl\n"
        f"\tld de, {MARKER}\n"
        "\tld hl, vTiles0 tile 'A'\n"
        f"\tlb bc, BANK({MARKER}), {FONT_TILES}\n"
        "\txor a\n"
        "\tldh [hRequestOpaque1bpp], a\n"
        "\tcall GetMaybeOpaque1bpp\n"
        "\tpop hl\n"
        "\tcall PrintText\n"
        "\tjmp LoadStandardFont\n\n"
    )
    new_common += (
        '\nSECTION "Classic Retro Arabic Elm Loader", ROMX\n'
        + routine
    )
    return {
        common: new_common.encode("utf-8"),
        intro: new_intro.encode("utf-8"),
        source / OUTPUT_FONT: asset.tiles,
    }


def prepare(source: Path, font_path: Path, preview: Path | None = None) -> dict[str, object]:
    """Apply only to an exact pinned, built source; leave original ROM unchanged."""
    source = Path(source).expanduser().resolve()
    font_path = Path(font_path).expanduser().resolve()
    _verify_upstream(source)
    for name, pinned in SOURCE_FILES.items():
        if _git_blob_sha((source / name).read_bytes()) != pinned:
            raise ClassicRetroError(ErrorCode.SOURCE_BASELINE_MISMATCH, f"{name} changed")
    if (source / OUTPUT_FONT).exists():
        raise ClassicRetroError(
            ErrorCode.OUTPUT_EXISTS, f"refusing existing {source / OUTPUT_FONT}"
        )
    if preview is not None and preview.exists():
        raise ClassicRetroError(ErrorCode.OUTPUT_EXISTS, f"refusing existing preview {preview}")
    assets = make_assets(source, font_path)
    changes = _source_overlays(source, assets)
    for path, data in changes.items():
        path.write_bytes(data)
    if preview is not None:
        image = Image.new("1", (COLUMNS * CELL_SIZE, len(assets.images) * 10))
        for index, line in enumerate(assets.images):
            image.paste(line, (0, index * 10))
        image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST).save(preview)
    return {
        "game": "polished-crystal",
        "scope": "ElmText1 only",
        "lines": len(assets.images),
        "atlas_tiles": FONT_TILES,
        "unique_arabic_tiles": assets.used_glyphs,
        "modified_source_files": [p.relative_to(source).as_posix() for p in changes],
        "rtl_mode": "static composed line cells",
        "dynamic_arabic": False,
        "playable_verified": False,
    }
