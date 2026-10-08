"""Subset the portfolio typefaces and record their advance widths.

Run only when the typefaces or the character set change. Rendering reads the
committed outputs and needs no third-party packages.

    pip install fonttools==4.66.0 brotli==1.2.0
    python scripts/fonts.py <directory holding inter.woff2 and inter-tight-heavy.woff2>
"""

import json
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

OUT = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Printable ASCII plus the punctuation the copy uses.
CHARACTERS = "".join(chr(c) for c in range(0x20, 0x7F)) + " ©·×–—‘’“”•…→"

FACES = {
    # key: (source file, weight to pin on a variable source)
    "inter-400": ("inter.woff2", 400),
    "inter-600": ("inter.woff2", 600),
    "inter-tight-900": ("inter-tight-heavy.woff2", None),
}


def build(source_dir: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metrics = {}
    for key, (filename, weight) in FACES.items():
        font = TTFont(source_dir / filename)
        if weight is not None and "fvar" in font:
            font = instancer.instantiateVariableFont(font, {"wght": weight})
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern", "calt", "liga"]
        options.name_IDs = ["*"]
        options.notdef_outline = True
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=CHARACTERS)
        subsetter.subset(font)
        font.flavor = "woff2"
        font.save(OUT / f"{key}.woff2")

        cmap = font.getBestCmap()
        hmtx = font["hmtx"].metrics
        metrics[key] = {
            "unitsPerEm": font["head"].unitsPerEm,
            "ascender": font["hhea"].ascent,
            "descender": font["hhea"].descent,
            "advances": {str(cp): hmtx[name][0] for cp, name in sorted(cmap.items())},
        }
    (OUT / "metrics.json").write_text(json.dumps(metrics, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(Path(sys.argv[1]))
