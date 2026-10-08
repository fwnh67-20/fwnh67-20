"""Render the profile README and its section artwork from profile/content.json.

Standard library only. Typography and colour follow the Tidal design system used
on the web portfolio: Inter Tight 900 for display, Inter 400/600 for text, and the
same light and dark tokens. Every section is drawn twice per theme, once for wide
and once for narrow viewports, and the README picks one with <picture> media queries.

    python scripts/render.py                       # write assets/*.svg and README.md
    python scripts/render.py --check               # fail if committed output is stale
    python scripts/render.py --activity FILE --out DIR   # write the activity card only
"""

import argparse
import base64
import html
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
CONTENT = json.loads((ROOT / "profile" / "content.json").read_text())
METRICS = json.loads((FONTS / "metrics.json").read_text())

FACES = {
    "display": ("Inter Tight", 900, "inter-tight-900"),
    "bold": ("Inter", 600, "inter-600"),
    "text": ("Inter", 400, "inter-400"),
}
FALLBACK = {"display": "Inter, system-ui, sans-serif", "bold": "system-ui, sans-serif", "text": "system-ui, sans-serif"}

# Tidal tokens, as defined in the portfolio's globals.css.
THEMES = {
    "light": {
        "primary": "#0e0f0c",
        "secondary": "#454745",
        "tertiary": "#6a6c6a",
        "link": "#0b5cad",
        "screen": "#ffffff",
        "subtle": "#f1f3f0",
        "neutral": "rgba(10,42,77,0.08)",
        "border": "rgba(14,15,12,0.12)",
        "mist": "#d6ecff",
        "control": "#0a2a4d",
        "positive": "#2f5711",
        "positiveBg": "#e2f6d5",
    },
    "dark": {
        "primary": "#e8ebe6",
        "secondary": "#c9cbc6",
        "tertiary": "#a0a39e",
        "link": "#8ecbff",
        "screen": "#121511",
        "subtle": "#1a1d19",
        "neutral": "rgba(142,203,255,0.12)",
        "border": "rgba(232,235,230,0.16)",
        "mist": "#16304a",
        "control": "#8ecbff",
        "positive": "#9fe870",
        "positiveBg": "#1d2a15",
    },
}
# Blue-deep bands keep one palette in both themes, as on the site.
BAND = {
    "bg": "#0a2a4d",
    "panel": "#08213b",
    "primary": "#e8ebe6",
    "secondary": "#c9cbc6",
    "tertiary": "#a0aeb8",
    "accent": "#8ecbff",
    "border": "#36516d",
    "chip": "#244767",
    "chipText": "#d6ecff",
}

LAYOUTS = {"wide": 880, "narrow": 400}
NARROW_QUERY = "(max-width: 640px)"


# ---------------------------------------------------------------- measuring


def measure(text: str, face: str, size: float, spacing: float = 0) -> float:
    metrics = METRICS[FACES[face][2]]
    units = sum(metrics["advances"].get(str(ord(ch)), 0.6 * metrics["unitsPerEm"]) for ch in text)
    return units / metrics["unitsPerEm"] * size + spacing * max(len(text) - 1, 0)


def baseline(top: float, face: str, size: float, line_height: float) -> float:
    """Baseline of a line box whose top edge is `top`, matching CSS half-leading."""
    metrics = METRICS[FACES[face][2]]
    ascent = metrics["ascender"] / metrics["unitsPerEm"] * size
    descent = -metrics["descender"] / metrics["unitsPerEm"] * size
    return top + (line_height - (ascent + descent)) / 2 + ascent


def wrap(text: str, face: str, size: float, width: float, spacing: float = 0) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and measure(candidate, face, size, spacing) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + ([current] if current else [])


def wrap_runs(runs: list[tuple[str, bool]], face: str, size: float, width: float) -> list[list[tuple[str, bool]]]:
    """Wrap styled runs word by word, keeping each word's emphasis."""
    words: list[tuple[str, bool, bool]] = []  # text, emphasis, joins previous word without a space
    spaced = True
    for text, emphasis in runs:
        for index, word in enumerate(text.split()):
            joined = index == 0 and not spaced and not text[:1].isspace()
            words.append((word, emphasis, joined))
        spaced = text[-1:].isspace()
    lines: list[list[tuple[str, bool]]] = []
    line: list[tuple[str, bool]] = []
    for word, emphasis, joined in words:
        piece = word if (joined or not line) else " " + word
        trial = "".join(t for t, _ in line) + piece
        if line and not joined and measure(trial, face, size) > width:
            lines.append(line)
            line = [(word, emphasis)]
        else:
            line.append((piece, emphasis))
    return lines + ([line] if line else [])


# ---------------------------------------------------------------- drawing


def esc(text: str) -> str:
    return html.escape(text, quote=True)


class Canvas:
    def __init__(self, width: int, theme: str):
        self.width = width
        self.theme = theme
        self.t = THEMES[theme]
        self.parts: list[str] = []
        self.faces: set[str] = set()

    def mark(self) -> int:
        return len(self.parts)

    def rect(self, x, y, w, h, fill, radius=0, at=None, stroke=None):
        attrs = f'x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}"'
        if radius:
            attrs += f' rx="{radius}"'
        if stroke:
            attrs += f' stroke="{stroke}"'
        element = f"<rect {attrs}/>"
        if at is None:
            self.parts.append(element)
        else:
            self.parts.insert(at, element)

    def hline(self, x, y, w, color, weight=1):
        self.rect(x, y, w, weight, color)

    def circle(self, cx, cy, r, fill, stroke=None, stroke_width=0):
        extra = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke else ""
        self.parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}"{extra}/>')

    def text(self, x, y, text, face, size, fill, anchor="start", spacing=0):
        self.faces.add(face)
        extra = f' text-anchor="{anchor}"' if anchor != "start" else ""
        if spacing:
            extra += f' letter-spacing="{spacing}"'
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" class="{face}" font-size="{size}" fill="{fill}"{extra}>{esc(text)}</text>'
        )

    def runs(self, x, y, runs, face, size, fill, accent):
        self.faces.add(face)
        spans = "".join(
            f'<tspan fill="{accent}">{esc(t)}</tspan>' if emphasis else esc(t) for t, emphasis in runs
        )
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}" class="{face}" font-size="{size}" fill="{fill}">{spans}</text>')

    def paragraph(self, x, top, text, face, size, line_height, fill, width, anchor="start", spacing=0, lines=None):
        """Draw wrapped text; return the bottom edge."""
        for line in lines or wrap(text, face, size, width, spacing):
            self.text(x, baseline(top, face, size, line_height), line, face, size, fill, anchor, spacing)
            top += line_height
        return top

    def chips(self, x, top, width, items, fill, color, size=13, height=28, pad=11, gap=7, face="bold"):
        """Flow pill chips left to right; return the bottom edge."""
        cx, cy = x, top
        for item in items:
            w = measure(item, face, size) + pad * 2
            if cx > x and cx + w > x + width:
                cx, cy = x, cy + height + gap
            self.rect(cx, cy, w, height, fill, radius=height / 2)
            self.text(cx + pad, baseline(cy, face, size, height), item, face, size, color)
            cx += w + gap
        return cy + height if items else top

    def svg(self, height: float, title: str) -> str:
        faces = []
        for face in sorted(self.faces):
            family, weight, key = FACES[face]
            data = base64.b64encode((FONTS / f"{key}.woff2").read_bytes()).decode()
            faces.append(
                f"@font-face{{font-family:'{family}';font-weight:{weight};font-display:block;"
                f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
                f".{face}{{font-family:'{family}',{FALLBACK[face]};font-weight:{weight};font-feature-settings:'calt'}}"
            )
        height = round(height)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{height}" '
            f'viewBox="0 0 {self.width} {height}" role="img" aria-label="{esc(title)}">'
            f"<title>{esc(title)}</title><style>{''.join(faces)}</style>"
            + "".join(self.parts)
            + "</svg>\n"
        )


class Scale:
    """Type and spacing for one layout width."""

    def __init__(self, layout: str):
        self.layout = layout
        self.narrow = layout == "narrow"
        self.width = LAYOUTS[layout]
        self.display = 40 if self.narrow else 64
        self.kicker = 15 if self.narrow else 18
        self.lede = 17 if self.narrow else 19
        self.band_pad = 24 if self.narrow else 48
        self.section_gap = 40 if self.narrow else 64
        self.columns = 1 if self.narrow else 2

    def column_width(self, inner: float, gap: float, columns: int | None = None) -> float:
        columns = columns or self.columns
        return (inner - gap * (columns - 1)) / columns


def display_title(c: Canvas, s: Scale, x, top, text, fill, width, anchor="start", size=None, lines=None):
    size = size or s.display
    return c.paragraph(x, top, text, "display", size, round(size * 0.94), fill, width, anchor, -0.3, lines)


def kicker(c: Canvas, s: Scale, x, top, text, fill, anchor="start"):
    line = round(s.kicker * 1.4)
    c.text(x, baseline(top, "bold", s.kicker, line), text, "bold", s.kicker, fill, anchor)
    return top + line + 14


# ---------------------------------------------------------------- sections


def hero(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    person = CONTENT["person"]
    mid = s.width / 2
    y = kicker(c, s, mid, 24 if s.narrow else 40, person["role"], c.t["link"], "middle")
    first, last = person["name"].split(" ", 1)
    lines = [first, last + "."]
    size = 120 if not s.narrow else 76
    while max(measure(line, "display", size, -0.6) for line in lines) > s.width - 8:
        size -= 2
    y = c.paragraph(mid, y + 4, "", "display", size, round(size * 0.88), c.t["primary"], s.width, "middle", -0.6, lines)
    summary = 19 if s.narrow else 24
    width = min(s.width, measure("0", "bold", summary) * 32)
    y = c.paragraph(mid, y + 28, person["summary"], "bold", summary, round(summary * 1.35), c.t["secondary"], width, "middle", -0.4)
    alt = f"{person['name']}. {person['role']}. {person['summary']}"
    return c.svg(y + (32 if s.narrow else 48), alt), alt


def format_moment(value: str | None, narrow: bool) -> str:
    if not value:
        return "unavailable"
    moment = datetime.fromisoformat(value).astimezone(ZoneInfo(CONTENT["person"]["timezone"]))
    label = moment.strftime("%-d %b %Y, %H:%M ") + moment.tzname()
    return label if narrow else moment.strftime("%a ") + label


def activity(theme: str, layout: str, data: dict) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, copy = c.t, CONTENT["activity"]
    pad = 24 if s.narrow else 40
    x, inner = pad, s.width - pad * 2
    background = c.mark()
    y = kicker(c, s, x, pad, copy["kicker"], t["link"])

    # Status pill
    status = "Last active · " + format_moment(data.get("lastActiveAt"), s.narrow)
    pill_h, size = 36, 13 if s.narrow else 14
    pill_w = measure(status, "bold", size) + 48
    c.rect(x, y, pill_w, pill_h, t["positiveBg"], radius=pill_h / 2)
    c.circle(x + 19, y + pill_h / 2, 5, t["positive"])
    c.text(x + 32, baseline(y, "bold", size, pill_h), status, "bold", size, t["positive"])
    y += pill_h + (24 if s.narrow else 32)

    # Figures
    window = data.get("windowDays", 30)
    figures = [
        (f"{data.get('contributionsWindow', 0):,}", ["contributions", f"last {window} days"]),
        (f"{data.get('contributionsYear', 0):,}", ["contributions", "last 12 months"]),
        (f"{data.get('activeRepositories', 0):,}", ["repositories active", f"last {window} days"]),
    ]
    gap = 16 if s.narrow else 32
    col = s.column_width(inner, gap, 3)
    number = 30 if s.narrow else 52
    label = 12 if s.narrow else 14
    bottom = y
    for index, (value, captions) in enumerate(figures):
        fx = x + index * (col + gap)
        fy = c.paragraph(fx, y, value, "display", number, round(number * 1.0), t["primary"], col, spacing=-0.3)
        for caption in captions:
            fy = c.paragraph(fx, fy + 2, caption, "text", label, round(label * 1.35), t["tertiary"], col)
        bottom = max(bottom, fy)
    y = bottom + (24 if s.narrow else 32)

    # Daily contributions
    daily = data.get("daily") or []
    if daily:
        chart_h = 48 if s.narrow else 72
        bar_gap = 2 if s.narrow else 4
        bar_w = (inner - bar_gap * (len(daily) - 1)) / len(daily)
        peak = max(daily) or 1
        for index, count in enumerate(daily):
            h = max(3, chart_h * count / peak)
            color = t["control"] if count else t["neutral"]
            c.rect(x + index * (bar_w + bar_gap), y + chart_h - h, bar_w, h, color, radius=min(3, bar_w / 2))
        y += chart_h + 10
        c.text(x, baseline(y, "text", 12, 16), f"Daily contributions, last {window} days", "text", 12, t["tertiary"])
        y += 16 + (20 if s.narrow else 28)

    # Languages
    languages = data.get("languages") or []
    if languages:
        y = c.paragraph(x, y, "Working in", "bold", 14, 20, t["primary"], inner) + 10
        y = c.chips(x, y, inner, languages, t["neutral"], t["primary"], size=14, height=34, pad=13) + (20 if s.narrow else 28)

    note = f"{copy['note']} Updated {format_moment(data.get('generatedAt'), True)}."
    y = c.paragraph(x, y, note, "text", 12, 17, t["tertiary"], inner)
    height = y + pad
    c.rect(0, 0, s.width, height, t["subtle"], radius=24, at=background)

    alt = (
        f"{copy['kicker']}. {status}. {figures[0][0]} contributions in the last {window} days, "
        f"{figures[1][0]} in the last 12 months, {figures[2][0]} repositories active in the last {window} days."
        + (f" Working in {', '.join(languages)}." if languages else "")
    )
    return c.svg(height + (16 if s.narrow else 24), alt), alt


def practice(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    copy = CONTENT["practice"]
    pad = s.band_pad
    x, inner = pad, s.width - pad * 2
    top = 16 if s.narrow else 24
    background = c.mark()
    y = kicker(c, s, x, top + pad, copy["kicker"], BAND["accent"])
    title = 32 if s.narrow else 52
    y = c.paragraph(x, y, copy["title"], "display", title, round(title * 0.97), BAND["primary"], min(inner, 760), spacing=-0.3)
    y += 28 if s.narrow else 44
    col_gap, row_gap = 32, 32 if s.narrow else 40
    col = s.column_width(inner, col_gap)
    word = 26 if s.narrow else 30
    for row_start in range(0, len(copy["areas"]), s.columns):
        row_bottom = y
        for offset, area in enumerate(copy["areas"][row_start : row_start + s.columns]):
            ax = x + offset * (col + col_gap)
            c.hline(ax, y, col, BAND["border"])
            ay = c.paragraph(ax, y + 20, area["word"], "display", word, round(word * 1.05), BAND["primary"], col, spacing=-0.3)
            ay = c.paragraph(ax, ay + 10, area["desc"], "text", 16, 24, BAND["secondary"], col)
            ay = c.chips(ax, ay + 16, col, area["chips"], BAND["chip"], BAND["chipText"])
            row_bottom = max(row_bottom, ay)
        y = row_bottom + row_gap
    height = y - row_gap + pad
    c.rect(0, top, s.width, height - top, BAND["bg"], radius=24, at=background)
    alt = f"{copy['kicker']}. {copy['title']} " + " ".join(f"{a['word']} {a['desc']}" for a in copy["areas"])
    return c.svg(height + top, alt), alt


def method(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, copy = c.t, CONTENT["method"]
    y = kicker(c, s, 0, s.section_gap, copy["kicker"], t["link"])
    y = display_title(c, s, 0, y, copy["title"], t["primary"], s.width)
    lede_width = min(s.width, measure("0", "text", s.lede) * 52)
    y = c.paragraph(0, y + 8, copy["lede"], "text", s.lede, round(s.lede * 1.47), t["secondary"], lede_width) + 36
    gap = 30
    col = s.column_width(s.width, gap)
    for row_start in range(0, len(copy["steps"]), s.columns):
        row_bottom = y
        for offset, step in enumerate(copy["steps"][row_start : row_start + s.columns]):
            x = offset * (col + gap)
            c.hline(x, y, col, t["border"])
            sy = c.paragraph(x, y + 24, step["label"], "bold", 14, 20, t["link"], col)
            sy = c.paragraph(x, sy + 8, step["title"], "display", 28, 31, t["primary"], col, spacing=-0.2)
            sy = c.paragraph(x, sy + 12, step["body"], "text", 16, 24, t["secondary"], col)
            row_bottom = max(row_bottom, sy)
        y = row_bottom + 32
    alt = f"{copy['kicker']}: {copy['title']} {copy['lede']} " + " ".join(f"{p['label']} {p['title']}: {p['body']}" for p in copy["steps"])
    return c.svg(y + 8, alt), alt


def expertise_tile(c: Canvas, s: Scale, x, y, w, domain, index, height=None) -> float:
    t = c.t
    style = index % 4
    fill = {0: t["subtle"], 1: t["mist"], 2: BAND["bg"], 3: t["subtle"]}[style]
    ink = BAND["primary"] if style == 2 else t["primary"]
    chip = BAND["chip"] if style == 2 else t["neutral"]
    pad = 24 if s.narrow else 32
    inner = w - pad * 2
    background = c.mark()
    ty = c.paragraph(x + pad, y + pad + 4, domain["kicker"], "bold", 14, 20, ink, inner)
    size = 28 if s.narrow else 32
    ty = c.paragraph(x + pad, ty + 12, domain["title"], "display", size, round(size * 1.0), ink, inner, spacing=-0.4)
    # Chips sit on the tile's bottom edge, like margin-top: auto on the site.
    probe = Canvas(c.width, c.theme)
    chips_h = probe.chips(0, 0, inner, domain["skills"], chip, ink) if domain["skills"] else 0
    natural = ty - y + 32 + chips_h + pad
    final = max(natural, height or 0, 0 if s.narrow else 300)
    c.chips(x + pad, y + final - pad - chips_h, inner, domain["skills"], chip, ink)
    c.rect(x, y, w, final, fill, radius=24, at=background)
    return final


def expertise(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, copy = c.t, CONTENT["expertise"]
    mid = s.width / 2
    y = display_title(c, s, mid, s.section_gap, copy["title"], t["primary"], s.width, "middle")
    lede_width = min(s.width, measure("0", "text", s.lede) * 44)
    y = c.paragraph(mid, y + 4, copy["lede"], "text", s.lede, 28, t["secondary"], lede_width, "middle") + 36
    gap = 16
    col = s.column_width(s.width, gap)
    domains = copy["domains"]
    for row_start in range(0, len(domains), s.columns):
        row = domains[row_start : row_start + s.columns]
        heights = [expertise_tile(Canvas(c.width, theme), s, 0, 0, col, d, row_start + i) for i, d in enumerate(row)]
        for offset, domain in enumerate(row):
            expertise_tile(c, s, offset * (col + gap), y, col, domain, row_start + offset, max(heights))
        y += max(heights) + gap
    alt = f"{copy['title']} {copy['lede']} " + " ".join(f"{d['kicker']}: {d['title']} ({', '.join(d['skills'])})." for d in domains)
    return c.svg(y + 8, alt), alt


def glance(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, copy = c.t, CONTENT["glance"]
    pad = s.band_pad
    top = s.section_gap - 16
    background = c.mark()
    y = kicker(c, s, pad, top + pad, copy["kicker"], t["link"])
    runs = [(text, emphasis) for text, emphasis in copy["runs"]]
    size = 28 if s.narrow else 46
    width = min(s.width - pad * 2, measure("0", "display", size) * 26)
    for line in wrap_runs(runs, "display", size, width):
        c.runs(pad, baseline(y, "display", size, size * 1.08), line, "display", size, t["primary"], t["link"])
        y += size * 1.08
    height = y + pad
    c.rect(0, top, s.width, height - top, t["subtle"], radius=24, at=background)
    alt = copy["kicker"] + ". " + "".join(text for text, _ in runs)
    return c.svg(height + 8, alt), alt


def career(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, roles = c.t, CONTENT["career"]["roles"]
    y = display_title(c, s, 0, s.section_gap, CONTENT["career"]["title"], t["primary"], s.width) + (16 if s.narrow else 32)
    rail = 8 if s.narrow else 185
    card_x = 32 if s.narrow else 215
    card_w = s.width - card_x
    line_marker = c.mark()
    first_dot = last_dot = None
    for role in roles:
        row = y
        if s.narrow:
            y = c.paragraph(card_x, y, role["period"], "bold", 13, 20, t["tertiary"], card_w) + 6
            dot = row + 10
        else:
            c.text(0, baseline(y + 18, "bold", 14, 20), role["period"], "bold", 14, t["tertiary"])
            dot = row + 28
        background = c.mark()
        pad = 18 if s.narrow else 22
        cy = c.paragraph(card_x + pad, y + 18, role["title"], "bold", 20 if s.narrow else 22, 27, t["primary"], card_w - pad * 2)
        cy = c.paragraph(card_x + pad, cy + 6, role["region"], "text", 14, 20, t["link"], card_w - pad * 2)
        cy = c.paragraph(card_x + pad, cy + 4, role["scope"], "text", 14, 20, t["tertiary"], card_w - pad * 2) + 18
        c.rect(card_x, y, card_w, cy - y, t["subtle"], radius=16, at=background)
        c.circle(rail, dot, 6.5, t["screen"], "#8ecbff", 3)
        first_dot = first_dot if first_dot is not None else dot
        last_dot = dot
        y = cy + (16 if s.narrow else 12)
    c.rect(rail - 2, first_dot, 4, last_dot - first_dot, "#8ecbff", radius=2, at=line_marker)
    alt = "Career. " + " ".join(f"{r['period']}: {r['title']}, {r['region']}. {r['scope']}." for r in roles)
    return c.svg(y + 8, alt), alt


def engagement_card(c: Canvas, x, y, w, item, height=None) -> float:
    pad = 24
    inner = w - pad * 2
    background = c.mark()
    meta = " · ".join(part for part in (item["where"], item["when"]) if part)
    ty = c.paragraph(x + pad, y + pad, meta, "bold", 12, 16, BAND["accent"], inner)
    ty = c.paragraph(x + pad, ty + 10, item["name"], "display", 22, 24, BAND["primary"], inner, spacing=-0.2)
    ty = c.paragraph(x + pad, ty + 10, item["desc"], "text", 14, 21, BAND["secondary"], inner)
    probe = Canvas(c.width, c.theme)
    chips_h = probe.chips(0, 0, inner, item["tags"], BAND["chip"], BAND["chipText"], size=12, height=26)
    final = max(ty - y + 16 + chips_h + pad, height or 0)
    c.chips(x + pad, y + final - pad - chips_h, inner, item["tags"], BAND["chip"], BAND["chipText"], size=12, height=26)
    c.rect(x, y, w, final, BAND["panel"], radius=20, at=background)
    return final


def engagements(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    copy = CONTENT["engagements"]
    pad = s.band_pad
    x, inner = pad, s.width - pad * 2
    top = s.section_gap - 16
    background = c.mark()
    y = kicker(c, s, x, top + pad, copy["kicker"], BAND["accent"])
    title = 32 if s.narrow else 52
    y = c.paragraph(x, y, copy["title"], "display", title, round(title * 0.97), BAND["primary"], inner, spacing=-0.3)
    y += 24 if s.narrow else 40
    items = copy["items"]
    if s.narrow:
        for item in items:
            y = c.paragraph(x, y + 13, item["name"], "bold", 15, 21, BAND["primary"], inner)
            meta = " · ".join(part for part in (item["where"], item["when"]) if part)
            y = c.paragraph(x, y + 2, meta, "text", 12, 17, BAND["tertiary"], inner) + 13
            c.hline(x, y, inner, BAND["border"])
            y += 1
    else:
        gap = 16
        col = s.column_width(inner, gap)
        for row_start in range(0, len(items), 2):
            row = items[row_start : row_start + 2]
            heights = [engagement_card(Canvas(c.width, theme), 0, 0, col, item) for item in row]
            for offset, item in enumerate(row):
                engagement_card(c, x + offset * (col + gap), y, col, item, max(heights))
            y += max(heights) + gap
        y -= gap
    height = y + pad
    c.rect(0, top, s.width, height - top, BAND["bg"], radius=24, at=background)
    alt = f"{copy['kicker']}. {copy['title']} " + " ".join(
        f"{i['name']}, {i['where']}{', ' + i['when'] if i['when'] else ''}: {i['desc']}" for i in items
    )
    return c.svg(height + 8, alt), alt


def credentials(theme: str, layout: str) -> tuple[str, str]:
    s, c = Scale(layout), Canvas(LAYOUTS[layout], theme)
    t, copy = c.t, CONTENT["credentials"]
    head, tail = copy["title"].split("& ")
    y = display_title(c, s, 0, s.section_gap, "", t["primary"], s.width, lines=[head + "&", tail]) + 24
    columns = 1 if s.narrow else 3
    gap = 30
    col = s.column_width(s.width, gap, columns)
    for row_start in range(0, len(copy["items"]), columns):
        row_bottom = y
        for offset, (name, detail) in enumerate(copy["items"][row_start : row_start + columns]):
            cx = offset * (col + gap)
            c.hline(cx, y, col, t["border"])
            cy = c.paragraph(cx, y + 24, name, "display", 26, 29, t["primary"], col, spacing=-0.2)
            cy = c.paragraph(cx, cy + 10, detail, "text", 14, 20, t["tertiary"], col)
            row_bottom = max(row_bottom, cy)
        y = row_bottom + (24 if s.narrow else 36)
    alt = copy["title"] + " " + " ".join(f"{name}: {detail}." for name, detail in copy["items"])
    return c.svg(y + 8, alt), alt


SECTIONS = {
    "hero": hero,
    "practice": practice,
    "method": method,
    "expertise": expertise,
    "glance": glance,
    "career": career,
    "engagements": engagements,
    "credentials": credentials,
}


# ---------------------------------------------------------------- README


def picture(base: str, name: str, alt: str, themed: bool = True) -> str:
    def src(theme: str, layout: str) -> str:
        return f"{base}{name}-{theme if themed else 'light'}-{layout}.svg"

    return (
        "<picture>\n"
        f'  <source media="{NARROW_QUERY} and (prefers-color-scheme: dark)" srcset="{src("dark", "narrow")}">\n'
        f'  <source media="{NARROW_QUERY}" srcset="{src("light", "narrow")}">\n'
        f'  <source media="(prefers-color-scheme: dark)" srcset="{src("dark", "wide")}">\n'
        f'  <img src="{src("light", "wide")}" width="100%" alt="{esc(alt)}">\n'
        "</picture>"
    )


def readme(alts: dict[str, str], shared: set[str]) -> str:
    person, profile = CONTENT["person"], CONTENT["profile"]
    activity_base = f"https://raw.githubusercontent.com/{profile['repository']}/{profile['activityBranch']}/"
    activity_alt = f"{CONTENT['activity']['kicker']}: when I last worked and how much, aggregated across private client repositories."
    blocks = [
        "<!-- Generated by scripts/render.py from profile/content.json. Edit the content, not this file. -->",
        picture("assets/", "hero", alts["hero"], "hero" not in shared),
        picture(activity_base, "activity", activity_alt),
        picture("assets/", "practice", alts["practice"], "practice" not in shared),
        picture("assets/", "method", alts["method"], "method" not in shared),
        picture("assets/", "expertise", alts["expertise"], "expertise" not in shared),
        picture("assets/", "glance", alts["glance"], "glance" not in shared),
        picture("assets/", "career", alts["career"], "career" not in shared),
    ]
    details = ["<details>", "<summary><b>Role details</b></summary>", ""]
    for role in CONTENT["career"]["roles"]:
        details += [f"#### {role['title']} · {role['region']}", f"<sub>{role['period']}</sub>", ""]
        details += [f"- {bullet}" for bullet in role["bullets"]] + [""]
    details.append("</details>")
    blocks.append("\n".join(details))
    blocks += [
        picture("assets/", "engagements", alts["engagements"], "engagements" not in shared),
        picture("assets/", "credentials", alts["credentials"], "credentials" not in shared),
        "---",
        f'<p align="center"><a href="{person["website"]}">{person["website"].removeprefix("https://")}</a>'
        f' · <a href="mailto:{person["email"]}">{person["email"]}</a></p>',
        f'<p align="center"><sub>© {person["name"]} · {person["practice"]}</sub></p>',
    ]
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------- entry points


def render_static(target: Path) -> dict[Path, str]:
    files, alts, shared = {}, {}, set()
    for name, draw in SECTIONS.items():
        drawn = {(theme, layout): draw(theme, layout) for theme in THEMES for layout in LAYOUTS}
        alts[name] = drawn["light", "wide"][1]
        # Blue-deep bands look the same in both themes; publish one file instead of two identical ones.
        if all(drawn["light", layout][0] == drawn["dark", layout][0] for layout in LAYOUTS):
            shared.add(name)
        for (theme, layout), (svg, _) in drawn.items():
            if theme == "light" or name not in shared:
                files[target / "assets" / f"{name}-{theme}-{layout}.svg"] = svg
    files[target / "README.md"] = readme(alts, shared)
    return files


def render_activity(data: dict, out: Path) -> dict[Path, str]:
    return {
        out / f"activity-{theme}-{layout}.svg": activity(theme, layout, data)[0]
        for theme in THEMES
        for layout in LAYOUTS
    }


def write(files: dict[Path, str]) -> None:
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit non-zero if committed output differs")
    parser.add_argument("--activity", type=Path, help="activity.json to render into an activity card")
    parser.add_argument("--out", type=Path, help="directory for the activity card")
    args = parser.parse_args()

    if args.activity:
        if not args.out:
            parser.error("--activity requires --out")
        write(render_activity(json.loads(args.activity.read_text()), args.out))
        return

    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            expected = {path.relative_to(scratch): text for path, text in render_static(Path(scratch)).items()}
        stale = [str(path) for path, text in expected.items() if not (ROOT / path).is_file() or (ROOT / path).read_text() != text]
        stale += [
            str(path.relative_to(ROOT)) for path in ASSETS.glob("*.svg") if path.relative_to(ROOT) not in expected
        ]
        if stale:
            sys.exit("Stale generated files; run python scripts/render.py:\n  " + "\n  ".join(stale))
        print("Generated files are current.")
        return

    write(render_static(ROOT))


if __name__ == "__main__":
    main()
