"""
Generates 3-4 slide LinkedIn carousel PDFs using Pillow.
Each slide is 1080x1080 px. Output: PDF for LinkedIn document upload + PNG preview.

Templates:
  list       — 4 slides: hook + content + content + CTA
  steps      — 4 slides: hook + steps1 + steps2 + CTA
  stat       — 3 slides: stat hook + insights + CTA
  comparison — 4 slides: hook + before + after + CTA
"""
import os
import platform
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Brand Colors (matched to The Tech Tutors logo) ───────────────────────────
# Logo palette: near-black background, yellow hero accent, teal secondary
BG_TOP    = (15,  15,  15)   # near-black charcoal (logo background)
BG_BOT    = (22,  22,  22)   # slightly lighter for subtle gradient
YELLOW    = (245, 197,  0)   # hero yellow — the big circle in logo (#F5C500)
YELLOW_DK = (180, 140,  0)   # darker yellow for shadows/depth
TEAL      = (0,   188, 188)  # teal — the AI brain/circuit accent (#00BCBC)
WHITE     = (255, 255, 255)
MUTED     = (155, 155, 155)  # muted gray for secondary text on dark bg
CARD_BG   = (28,  28,  28)   # dark charcoal card background
DARK_BG2  = (10,  10,  10)   # deepest dark for accents

# Legacy aliases kept for backward compat with old slide functions
BLUE      = TEAL
BLUE_LT   = TEAL
DARK_BLUE = (0,   80,  80)

CANVAS_W = 1080
CANVAS_H = 1080
PAD      = 68

LOGO_PATH  = Path(__file__).parent.parent / "TTT" / "Logo.jpg"
OUTPUT_DIR = Path(__file__).parent / "output"

# Platform-aware font discovery. Each logical name maps to a list of real font
# files to probe across known font directories. On GitHub Actions (Ubuntu) the
# DejaVu / Liberation families are preinstalled; on Windows we keep Arial.
_SYSTEM = platform.system()
if _SYSTEM == "Windows":
    FONT_DIRS = ["C:/Windows/Fonts/"]
elif _SYSTEM == "Darwin":
    FONT_DIRS = ["/Library/Fonts/", "/System/Library/Fonts/", "/System/Library/Fonts/Supplemental/"]
else:
    FONT_DIRS = [
        "/usr/share/fonts/truetype/dejavu/",
        "/usr/share/fonts/truetype/liberation/",
        "/usr/share/fonts/truetype/freefont/",
        "/usr/share/fonts/TTF/",
    ]

# Logical name → ordered candidate filenames. First match wins.
_FONT_FALLBACKS = {
    "arialbd.ttf": ["arialbd.ttf", "DejaVuSans-Bold.ttf",  "LiberationSans-Bold.ttf",    "FreeSansBold.ttf"],
    "arial.ttf":   ["arial.ttf",   "DejaVuSans.ttf",       "LiberationSans-Regular.ttf", "FreeSans.ttf"],
    "ariblk.ttf":  ["ariblk.ttf",  "DejaVuSans-Bold.ttf",  "LiberationSans-Bold.ttf",    "FreeSansBold.ttf"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = _FONT_FALLBACKS.get(name, [name, "arialbd.ttf", "arial.ttf"])
    for fdir in FONT_DIRS:
        for fname in candidates:
            try:
                return ImageFont.truetype(os.path.join(fdir, fname), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(CANVAS_H):
        t = y / CANVAS_H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (CANVAS_W, y)], fill=(r, g, b))
    return img, draw


def _wrap(text: str, font, draw: ImageDraw.ImageDraw, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), cand, font=font)[2] <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_brand_circles(draw: ImageDraw.ImageDraw):
    """Draw decorative yellow/teal circles matching the logo aesthetic."""
    # Large yellow circle (top-right, partially off-canvas — like logo's hero circle)
    draw.ellipse([(CANVAS_W - 160, -160), (CANVAS_W + 120, 120)], fill=YELLOW_DK)
    # Small teal circle (bottom-left — secondary accent)
    draw.ellipse([(-60, CANVAS_H - 120), (80, CANVAS_H + 60)], fill=(0, 80, 80))
    # Tiny yellow dot (bottom-right)
    draw.ellipse([(CANVAS_W - 50, CANVAS_H - 80), (CANVAS_W + 10, CANVAS_H - 20)], fill=YELLOW_DK)


def _top_bar(draw: ImageDraw.ImageDraw, slide_num: int, total: int) -> int:
    # Yellow top accent line
    draw.rectangle([(0, 0), (CANVAS_W, 6)], fill=YELLOW)
    f = _f("arialbd.ttf", 22)
    draw.text((PAD, 18), "THE TECH TUTORS", font=f, fill=YELLOW)
    counter = f"{slide_num} / {total}"
    cw = draw.textbbox((0, 0), counter, font=f)[2]
    draw.text((CANVAS_W - PAD - cw, 18), counter, font=f, fill=MUTED)
    return 68


def _bottom_bar(img: Image.Image, draw: ImageDraw.ImageDraw):
    bar_y = CANVAS_H - 68
    draw.rectangle([(0, bar_y), (CANVAS_W, CANVAS_H)], fill=DARK_BG2)
    draw.rectangle([(0, bar_y), (CANVAS_W, bar_y + 3)], fill=YELLOW)
    f = _f("arial.ttf", 20)
    tx = PAD
    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((42, 42))
            img.paste(logo, (PAD, bar_y + 13), logo)
            tx = PAD + 54
        except Exception:
            pass
    draw.text((tx, bar_y + 22), "AI Tools & Automations for Businesses", font=f, fill=MUTED)
    site = "the-tech-tutors.vercel.app"
    sw = draw.textbbox((0, 0), site, font=f)[2]
    draw.text((CANVAS_W - PAD - sw, bar_y + 22), site, font=f, fill=TEAL)


# ═══════════════════════════════════════════════════════════════════════════════
# NEW CAROUSEL SYSTEM — 5 fixed slide layouts
# ═══════════════════════════════════════════════════════════════════════════════

def _slide_hook(data: dict, num: int, total: int) -> Image.Image:
    """Slide 1 — HOOK: dark bg, yellow headline, teal subheadline, logo circles."""
    img, draw = _canvas()
    _draw_brand_circles(draw)

    y = _top_bar(draw, num, total)
    content_w = CANVAS_W - 2 * PAD

    # Large yellow headline — all caps, bold
    f_head = _f("ariblk.ttf", 68)
    headline = data.get("headline", "").upper()
    lines = _wrap(headline, f_head, draw, content_w)[:3]
    total_h = len(lines) * 82 + 24 + 56
    ty = (CANVAS_H - 68 - y) // 2 + y - total_h // 2

    for line in lines:
        lw = draw.textbbox((0, 0), line, font=f_head)[2]
        # Shadow
        draw.text(((CANVAS_W - lw) // 2 + 3, ty + 3), line, font=f_head, fill=YELLOW_DK)
        draw.text(((CANVAS_W - lw) // 2, ty), line, font=f_head, fill=YELLOW)
        ty += 82

    # Yellow divider
    ty += 8
    draw.rectangle([(CANVAS_W // 2 - 80, ty), (CANVAS_W // 2 + 80, ty + 5)], fill=YELLOW)
    ty += 22

    # Teal subheadline
    f_sub = _f("arialbd.ttf", 28)
    for line in _wrap(data.get("subheadline", ""), f_sub, draw, content_w - 80)[:2]:
        lw = draw.textbbox((0, 0), line, font=f_sub)[2]
        draw.text(((CANVAS_W - lw) // 2, ty), line, font=f_sub, fill=TEAL)
        ty += 42

    # Swipe prompt
    ty += 18
    f_swipe = _f("arial.ttf", 21)
    swipe = "Swipe to learn more  ->"
    sw = draw.textbbox((0, 0), swipe, font=f_swipe)[2]
    draw.text(((CANVAS_W - sw) // 2, ty), swipe, font=f_swipe, fill=MUTED)

    _bottom_bar(img, draw)
    return img


def _slide_situation(data: dict, num: int, total: int) -> Image.Image:
    """Slide 2 — SITUATION: 3 stat cards, yellow accent numbers."""
    img, draw = _canvas()
    _draw_brand_circles(draw)

    y = _top_bar(draw, num, total) + 14

    f_sec     = _f("arialbd.ttf", 32)
    f_stat    = _f("ariblk.ttf",  52)
    f_context = _f("arialbd.ttf", 24)

    title = data.get("section_title", "WHAT'S HAPPENING")
    draw.text((PAD, y), title, font=f_sec, fill=YELLOW)
    y += 42
    tw = draw.textbbox((0, 0), title, font=f_sec)[2]
    draw.rectangle([(PAD, y), (PAD + tw, y + 4)], fill=YELLOW)
    y += 18

    stats = data.get("stats", [])[:3]
    avail = CANVAS_H - 68 - y - 14
    card_h = min((avail - (len(stats) - 1) * 12) // max(len(stats), 1), 175)

    for i, item in enumerate(stats):
        cy = y + i * (card_h + 12)
        draw.rounded_rectangle([(PAD, cy), (CANVAS_W - PAD, cy + card_h)], radius=12, fill=CARD_BG)
        # Yellow left accent bar
        draw.rounded_rectangle([(PAD, cy), (PAD + 7, cy + card_h)], radius=12, fill=YELLOW)

        stat_text = item.get("stat", "")
        stw = draw.textbbox((0, 0), stat_text, font=f_stat)[2]
        draw.text((PAD + 26, cy + (card_h - 56) // 2), stat_text, font=f_stat, fill=YELLOW)

        ctx_x = PAD + 26 + stw + 18
        ctx_w = CANVAS_W - PAD - ctx_x - 10
        ctx_lines = _wrap(item.get("context", ""), f_context, draw, ctx_w)[:3]
        ctx_y = cy + (card_h - len(ctx_lines) * 32) // 2
        for ln in ctx_lines:
            draw.text((ctx_x, ctx_y), ln, font=f_context, fill=WHITE)
            ctx_y += 32

    _bottom_bar(img, draw)
    return img


def _slide_impact(data: dict, num: int, total: int) -> Image.Image:
    """Slide 3 — IMPACT: 3 cards, teal numbered circles, yellow title."""
    img, draw = _canvas()
    _draw_brand_circles(draw)

    y = _top_bar(draw, num, total) + 14

    f_sec    = _f("arialbd.ttf", 26)
    f_title  = _f("arialbd.ttf", 26)
    f_detail = _f("arial.ttf",   22)
    f_num    = _f("ariblk.ttf",  36)

    title = data.get("section_title", "WHY YOUR BUSINESS IS AFFECTED")
    draw.text((PAD, y), title, font=f_sec, fill=YELLOW)
    y += 38
    tw = draw.textbbox((0, 0), title, font=f_sec)[2]
    draw.rectangle([(PAD, y), (min(PAD + tw, CANVAS_W - PAD), y + 4)], fill=YELLOW)
    y += 20

    impacts = data.get("impacts", [])[:3]
    avail   = CANVAS_H - 68 - y - 14
    card_h  = min((avail - (len(impacts) - 1) * 10) // max(len(impacts), 1), 188)

    for i, item in enumerate(impacts):
        cy = y + i * (card_h + 10)
        draw.rounded_rectangle([(PAD, cy), (CANVAS_W - PAD, cy + card_h)], radius=12, fill=CARD_BG)
        draw.rounded_rectangle([(PAD, cy), (PAD + 7, cy + card_h)], radius=12, fill=TEAL)

        # Teal numbered circle
        ncx, ncy, r = PAD + 44, cy + card_h // 2, 26
        draw.ellipse([(ncx - r, ncy - r), (ncx + r, ncy + r)], fill=TEAL)
        ns = str(i + 1)
        nw = draw.textbbox((0, 0), ns, font=f_num)[2]
        draw.text((ncx - nw // 2, ncy - 22), ns, font=f_num, fill=(10, 10, 10))

        tx, tw2 = PAD + 86, CANVAS_W - 2 * PAD - 86
        t_lines = _wrap(item.get("title", ""), f_title, draw, tw2)[:1]
        d_lines = _wrap(item.get("detail", ""), f_detail, draw, tw2)[:2]
        th = len(t_lines) * 34 + len(d_lines) * 28
        ts = cy + (card_h - th) // 2
        for ln in t_lines:
            draw.text((tx, ts), ln, font=f_title, fill=WHITE)
            ts += 34
        for ln in d_lines:
            draw.text((tx, ts), ln, font=f_detail, fill=MUTED)
            ts += 28

    _bottom_bar(img, draw)
    return img


def _slide_action(data: dict, num: int, total: int) -> Image.Image:
    """Slide 4 — ACTION PLAN: yellow step numbers, teal separator."""
    img, draw = _canvas()
    _draw_brand_circles(draw)

    y = _top_bar(draw, num, total) + 14

    f_sec    = _f("arialbd.ttf", 32)
    f_action = _f("arialbd.ttf", 25)
    f_detail = _f("arial.ttf",   21)
    f_num    = _f("ariblk.ttf",  54)

    title = data.get("section_title", "YOUR ACTION PLAN")
    draw.text((PAD, y), title, font=f_sec, fill=YELLOW)
    y += 42
    tw = draw.textbbox((0, 0), title, font=f_sec)[2]
    draw.rectangle([(PAD, y), (PAD + tw, y + 4)], fill=YELLOW)
    y += 20

    steps     = data.get("steps", [])[:3]
    avail     = CANVAS_H - 68 - y - 14
    card_h    = min((avail - (len(steps) - 1) * 12) // max(len(steps), 1), 195)

    for i, step in enumerate(steps):
        cy = y + i * (card_h + 12)
        draw.rounded_rectangle([(PAD, cy), (CANVAS_W - PAD, cy + card_h)], radius=12, fill=CARD_BG)

        # Big yellow step number
        num_text = str(i + 1)
        nw = draw.textbbox((0, 0), num_text, font=f_num)[2]
        draw.text((PAD + 20, cy + (card_h - 58) // 2), num_text, font=f_num, fill=YELLOW)

        # Teal vertical separator
        sep_x = PAD + 20 + nw + 16
        draw.rectangle([(sep_x, cy + 16), (sep_x + 3, cy + card_h - 16)], fill=TEAL)

        tx, tw2 = sep_x + 18, CANVAS_W - PAD - sep_x - 22
        a_lines = _wrap(step.get("action", ""), f_action, draw, tw2)[:1]
        d_lines = _wrap(step.get("detail", ""), f_detail, draw, tw2)[:2]
        th = len(a_lines) * 32 + len(d_lines) * 28
        ts = cy + (card_h - th) // 2
        for ln in a_lines:
            draw.text((tx, ts), ln, font=f_action, fill=WHITE)
            ts += 32
        for ln in d_lines:
            draw.text((tx, ts), ln, font=f_detail, fill=MUTED)
            ts += 28

    _bottom_bar(img, draw)
    return img


def _slide_cta(data: dict, num: int, total: int) -> Image.Image:
    """Slide 5 — TAKEAWAY + CTA: large yellow circles, quotable statement."""
    img, draw = _canvas()

    # Hero yellow circle (large, center-right) — mirrors logo
    draw.ellipse([(CANVAS_W - 340, CANVAS_H // 2 - 280), (CANVAS_W + 80, CANVAS_H // 2 + 280)], fill=YELLOW_DK)
    # Teal corner accent
    draw.ellipse([(-80, CANVAS_H - 200), (120, CANVAS_H + 60)], fill=(0, 60, 60))
    # Small yellow bottom-right
    draw.ellipse([(CANVAS_W - 80, CANVAS_H - 100), (CANVAS_W + 20, CANVAS_H)], fill=YELLOW_DK)

    # Top bar (manual — CTA slide has custom header)
    draw.rectangle([(0, 0), (CANVAS_W, 6)], fill=YELLOW)
    f_brand = _f("arialbd.ttf", 22)
    draw.text((PAD, 18), "THE TECH TUTORS", font=f_brand, fill=YELLOW)
    counter = f"{num} / {total}"
    cw = draw.textbbox((0, 0), counter, font=f_brand)[2]
    draw.text((CANVAS_W - PAD - cw, 18), counter, font=f_brand, fill=MUTED)

    content_w = CANVAS_W - 2 * PAD
    cy = CANVAS_H // 2 - 150

    # Quotable takeaway
    f_quote = _f("arialbd.ttf", 30)
    takeaway = '"' + data.get("takeaway", "") + '"'
    q_lines = _wrap(takeaway, f_quote, draw, content_w - 120)[:4]
    for line in q_lines:
        lw = draw.textbbox((0, 0), line, font=f_quote)[2]
        draw.text(((CANVAS_W - lw) // 2, cy), line, font=f_quote, fill=WHITE)
        cy += 42

    cy += 18
    draw.rectangle([(CANVAS_W // 2 - 70, cy), (CANVAS_W // 2 + 70, cy + 4)], fill=YELLOW)
    cy += 26

    # "Follow" CTA
    f_follow = _f("ariblk.ttf", 34)
    follow = "Follow The Tech Tutors"
    fw = draw.textbbox((0, 0), follow, font=f_follow)[2]
    draw.text(((CANVAS_W - fw) // 2, cy), follow, font=f_follow, fill=YELLOW)
    cy += 48

    f_sub = _f("arial.ttf", 22)
    sub = "for weekly AI insights that grow your business"
    subw = draw.textbbox((0, 0), sub, font=f_sub)[2]
    draw.text(((CANVAS_W - subw) // 2, cy), sub, font=f_sub, fill=MUTED)
    cy += 50

    # Logo
    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((70, 70))
            img.paste(logo, ((CANVAS_W - 70) // 2, cy), logo)
        except Exception:
            pass

    # Footer
    draw.rectangle([(0, CANVAS_H - 52), (CANVAS_W, CANVAS_H)], fill=DARK_BG2)
    f_site = _f("arialbd.ttf", 21)
    site = "the-tech-tutors.vercel.app"
    sw = draw.textbbox((0, 0), site, font=f_site)[2]
    draw.text(((CANVAS_W - sw) // 2, CANVAS_H - 40), site, font=f_site, fill=TEAL)

    return img


def generate_carousel_slides(content: dict, date_str: str) -> tuple[str, str]:
    """Build 5-slide carousel PDF from structured content. Returns (pdf_path, preview_png_path)."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    total = 5
    slides = [
        _slide_hook(content.get("slide1", {}), 1, total),
        _slide_situation(content.get("slide2", {}), 2, total),
        _slide_impact(content.get("slide3", {}), 3, total),
        _slide_action(content.get("slide4", {}), 4, total),
        _slide_cta(content.get("slide5", {}), 5, total),
    ]

    pdf_path     = str(OUTPUT_DIR / f"{date_str}_carousel.pdf")
    preview_path = str(OUTPUT_DIR / f"{date_str}_slide1.png")
    slides[0].save(pdf_path, save_all=True, append_images=slides[1:])
    slides[0].save(preview_path, "PNG")
    print(f"  [designer] 5 slides -> {pdf_path}")
    return pdf_path, preview_path
