"""
Generates a branded 1200x1200 PNG from a design brief using Pillow.
Templates: list (default), steps, comparison, stat
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG_COLOR = "#0D1B2A"
WHITE    = "#FFFFFF"
BLUE     = "#0EA5E9"
MUTED    = "#8BA3C1"

CANVAS_W, CANVAS_H = 1200, 1200
PADDING = 80

LOGO_PATH  = Path(__file__).parent.parent / "TTT" / "Logo.jpg"
OUTPUT_DIR = Path(__file__).parent / "output"
FONT_DIR   = "C:/Windows/Fonts/"


def _load_font(name: str, size: int):
    try:
        return ImageFont.truetype(f"{FONT_DIR}{name}", size)
    except OSError:
        return ImageFont.load_default()


def _make_fonts() -> dict:
    return {
        "brand":    _load_font("arialbd.ttf", 26),
        "title":    _load_font("arialbd.ttf", 58),
        "body":     _load_font("arial.ttf",   34),
        "body_sm":  _load_font("arial.ttf",   28),
        "small":    _load_font("arial.ttf",   26),
        "step_num": _load_font("arialbd.ttf", 72),
        "stat":     _load_font("arialbd.ttf", 90),
    }


def _wrap(text: str, font, draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# ── Shared header / footer ──────────────────────────────────────────────────

def _draw_header(img: Image.Image, draw: ImageDraw.ImageDraw, f: dict, brief: dict) -> int:
    content_w = CANVAS_W - 2 * PADDING
    y = PADDING

    draw.text((PADDING, y), "THE TECH TUTORS", font=f["brand"], fill=BLUE)
    y += 44
    draw.line([(PADDING, y), (CANVAS_W - PADDING, y)], fill=BLUE, width=2)
    y += 36

    for line in _wrap(brief.get("graphic_title", "").upper(), f["title"], draw, content_w)[:3]:
        draw.text((PADDING, y), line, font=f["title"], fill=WHITE)
        y += 74
    y += 16

    draw.line([(PADDING, y), (CANVAS_W - PADDING, y)], fill=BLUE, width=2)
    y += 36

    layout = brief.get("graphic_layout", "")
    if layout:
        draw.text((PADDING, y), layout.upper(), font=f["small"], fill=MUTED)
        y += 38
    return y + 8


def _draw_footer(img: Image.Image, draw: ImageDraw.ImageDraw, f: dict):
    logo_y = CANVAS_H - PADDING - 72
    tagline_x = PADDING
    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((72, 72))
            img.paste(logo, (PADDING, logo_y), logo)
            tagline_x = PADDING + 82
        except Exception:
            pass
    draw.text(
        (tagline_x, logo_y + 22),
        "We build AI tools & automations for businesses.",
        font=f["small"],
        fill=MUTED,
    )


# ── Layout templates ────────────────────────────────────────────────────────

def _layout_list(draw: ImageDraw.ImageDraw, f: dict, points: list[str], y: int) -> int:
    content_w = CANVAS_W - 2 * PADDING
    r = 7
    for point in points[:5]:
        draw.ellipse([(PADDING, y + 13), (PADDING + r * 2, y + 13 + r * 2)], fill=BLUE)
        for i, line in enumerate(_wrap(point, f["body"], draw, content_w - 28)[:2]):
            draw.text((PADDING + 26, y + i * 46), line, font=f["body"], fill=WHITE)
        y += 66 + 14
    return y


def _layout_steps(draw: ImageDraw.ImageDraw, f: dict, points: list[str], y: int) -> int:
    content_w = CANVAS_W - 2 * PADDING
    for i, point in enumerate(points[:5], 1):
        num = f"{i:02d}"
        num_w = draw.textbbox((0, 0), num, font=f["step_num"])[2] + 24
        draw.text((PADDING, y), num, font=f["step_num"], fill=BLUE)
        for j, line in enumerate(_wrap(point, f["body"], draw, content_w - num_w)[:2]):
            draw.text((PADDING + num_w, y + 20 + j * 44), line, font=f["body"], fill=WHITE)
        y += max(88, 44 + 20) + 16
    return y


def _layout_comparison(draw: ImageDraw.ImageDraw, f: dict, points: list[str], y: int, title: str) -> int:
    content_w = CANVAS_W - 2 * PADDING
    col_w = (content_w - 40) // 2
    mid_x = PADDING + col_w + 20

    if " vs " in title.lower():
        parts = title.lower().split(" vs ", 1)
        h1 = parts[0].strip().upper()[:20]
        h2 = parts[1].strip().upper()[:20]
    else:
        h1, h2 = "WITHOUT AI", "WITH AI"

    draw.text((PADDING, y), h1, font=f["small"], fill=BLUE)
    draw.text((PADDING + col_w + 40, y), h2, font=f["small"], fill=BLUE)
    y += 36
    start_y = y

    col1 = points[0::2][:3]
    col2 = points[1::2][:3]

    for i in range(max(len(col1), len(col2))):
        row_h = 56
        if i < len(col1):
            lines = _wrap(f"• {col1[i]}", f["body_sm"], draw, col_w - 10)[:2]
            for j, line in enumerate(lines):
                draw.text((PADDING, y + j * 40), line, font=f["body_sm"], fill=WHITE)
            row_h = max(row_h, len(lines) * 40)
        if i < len(col2):
            lines = _wrap(f"• {col2[i]}", f["body_sm"], draw, col_w - 10)[:2]
            for j, line in enumerate(lines):
                draw.text((PADDING + col_w + 40, y + j * 40), line, font=f["body_sm"], fill=WHITE)
            row_h = max(row_h, len(lines) * 40)
        y += row_h + 12

    draw.line([(mid_x, start_y), (mid_x, y)], fill=BLUE, width=1)
    return y


def _layout_stat(draw: ImageDraw.ImageDraw, f: dict, points: list[str], y: int) -> int:
    content_w = CANVAS_W - 2 * PADDING
    if not points:
        return y

    for line in _wrap(points[0], f["stat"], draw, content_w)[:2]:
        w = draw.textbbox((0, 0), line, font=f["stat"])[2]
        draw.text(((CANVAS_W - w) // 2, y), line, font=f["stat"], fill=BLUE)
        y += 110
    y += 20

    draw.line([(PADDING, y), (CANVAS_W - PADDING, y)], fill=BLUE, width=1)
    y += 28

    for point in points[1:4]:
        for line in _wrap(f"• {point}", f["body_sm"], draw, content_w)[:2]:
            draw.text((PADDING, y), line, font=f["body_sm"], fill=WHITE)
            y += 40
        y += 8
    return y


# ── Public entry point ───────────────────────────────────────────────────────

def generate_graphic(brief: dict, date_str: str) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = str(OUTPUT_DIR / f"{date_str}_graphic.png")

    img  = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    f    = _make_fonts()

    y      = _draw_header(img, draw, f, brief)
    points = brief.get("graphic_points", [])
    title  = brief.get("graphic_title", "")

    template = brief.get("template", "list")
    if template == "steps":
        _layout_steps(draw, f, points, y)
    elif template == "comparison":
        _layout_comparison(draw, f, points, y, title)
    elif template == "stat":
        _layout_stat(draw, f, points, y)
    else:
        _layout_list(draw, f, points, y)

    _draw_footer(img, draw, f)
    img.save(out_path, "PNG")
    return out_path
