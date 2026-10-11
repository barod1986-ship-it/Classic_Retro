"""The Arabic lettering of Polished Crystal's tile graphics, without the game's files."""

from __future__ import annotations

import pytest

from classic_retro.source import polished_crystal_arabic as overlay
from classic_retro.source.polished_crystal import gfx_labels


def test_a_label_is_laid_out_right_to_left_from_the_overlay_glyphs():
    small = gfx_labels.render("نوم")
    assert len(small) == gfx_labels.SMALL.height and sum(row.count("#") for row in small) > 10
    big = gfx_labels.render("الأدوات", gfx_labels.BIG)
    assert len(big) == 8 and gfx_labels.width(big) > gfx_labels.width(small)
    # the first letter is on the right: a word and its letters reversed differ
    assert gfx_labels.render("نم") != gfx_labels.render("من")
    # button names keep their order inside the Arabic
    assert gfx_labels.render("A◀وصف")
    with pytest.raises(ValueError, match="no glyph"):
        gfx_labels.render("Items")
    turned = gfx_labels.rotate_ccw(small)
    assert len(turned) == gfx_labels.width(small) and len(turned[0]) == len(small)


def test_the_lettering_is_drawn_only_over_the_pinned_originals():
    assert set(gfx_labels.paths()) <= set(overlay.generated_files())
    assert set(gfx_labels.paths()) <= set(gfx_labels.pristine_sha256())
    assert all(len(digest) == 64 for digest in gfx_labels.pristine_sha256().values())
    # every file it reads is pinned, so prepare refuses a changed checkout first
    pins = overlay.pinned_blobs()
    assert set(gfx_labels.pristine_sha256()) <= set(pins)
    with pytest.raises(gfx_labels.PristineMismatch, match="not the pristine file"):
        gfx_labels.outputs(lambda path: b"not the original")
