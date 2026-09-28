"""The libraries a build runs on, recorded so its outputs can be reproduced.

Every glyph is rasterized by the FreeType bundled in the installed Pillow
wheel and shaped by the HarfBuzz bundled in uharfbuzz; a FreeType release
changes most glyph forms, and with them every patch. Every report carries
these versions under ``raster`` and ``constraints.txt`` pins them, so a patch
hash or a translation digest names the versions it was made with.
"""

from __future__ import annotations

import platform
from importlib.metadata import version

import uharfbuzz
from PIL import __version__ as pillow_version
from PIL import features


def library_versions() -> dict[str, str]:
    """The rasterization stack and its neighbours, by short name.

    ``freetype`` is the library Pillow was built with (the one drawing the
    glyphs); ``harfbuzz`` is the uharfbuzz binding, which bundles its own copy
    of the library. The rest are the installed distributions: arabic_reshaper's
    module version lags its releases, so none is read from a module attribute.
    """
    return {
        "pillow": pillow_version,
        "freetype": features.version_module("freetype2") or "unavailable",
        "harfbuzz": uharfbuzz.__version__,
        "fonttools": version("fonttools"),
        "arabic_reshaper": version("arabic-reshaper"),
        "python_bidi": version("python-bidi"),
        "jsonschema": version("jsonschema"),
        "pycdlib": version("pycdlib"),
        "python": platform.python_version(),
    }
