"""
Generates 3-4 slide LinkedIn carousel PDFs using Pillow.
Each slide is 1080x1080 px. Output: PDF for LinkedIn document upload + PNG preview.

Templates:
  list       — 4 slides: hook + content + content + CTA
  steps      — 4 slides: hook + steps1 + steps2 + CTA
  stat       — 3 slides: stat hook + insights + CTA
  comparison — 4 slides: hook + before + after + CTA
"""
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
DARK_LINE = (45,  45,  45)   # subtle separator on dark bg
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
FONT_DIR   = "C:/Windows/Fonts/"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(name: str, size: int) -> ImageFont.FreeTypeFont:
    for fname in [name, "arialbd.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(f"{FONT_DIR}{fname}", size)
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


def _draw_brand_circles(draw: ImageDraw.ImageDraw, opacity_hint: str = "normal"):
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


# ── Slide 1: Hook ─────────────────────────────────────────────────────────────

def _hook_slide(brief: dict, slide_num: int, total: int) -> Image.Image:
    img, draw = _canvas()
    draw.ellipse([(CANVAS_W - 240, -120), (CANVAS_W + 60, 180)], fill=DARK_BLUE)
    draw.ellipse([(-60, CANVAS_H - 200), (180, CANVAS_H + 60)], fill=DARK_BLUE)

    y = _top_bar(draw, slide_num, total)
    content_w = CANVAS_W - 2 * PAD
    title = brief.get("graphic_title", "").upper()
    subtext = brief.get("hook_subtext", "Swipe to learn more")

    font = _f("ariblk.ttf", 82)
    lines = _wrap(title, font, draw, content_w)[:4]
    total_h = len(lines) * 94 + 60 + 50
    ty = (CANVAS_H - 72 - y) // 2 + y - total_h // 2

    for line in lines:
        lw = draw.textbbox((0, 0), line, font=font)[2]
        draw.text(((CANVAS_W - lw) // 2 + 3, ty + 3), line, font=font, fill=(5, 15, 30))
        draw.text(((CANVAS_W - lw) // 2, ty), line, font=font, fill=WHITE)
        ty += 94

    ty += 16
    draw.rectangle([(CANVAS_W // 2 - 80, ty), (CANVAS_W // 2 + 80, ty + 5)], fill=BLUE)
    ty += 28

    f_sub = _f("arialbd.ttf", 34)
    for line in _wrap(f"{subtext}  →", f_sub, draw, content_w - 40)[:2]:
        lw = draw.textbbox((0, 0), line, font=f_sub)[2]
        draw.text(((CANVAS_W - lw) // 2, ty), line, font=f_sub, fill=BLUE_LT)
        ty += 48

    _bottom_bar(img, draw)
    return img


# ── Slides 2-3: Content ───────────────────────────────────────────────────────

def _content_slide(
    points: list[str],
    section_title: str,
    slide_num: int,
    total: int,
    emoji: str = "",
) -> Image.Image:
    img, draw = _canvas()
    y = _top_bar(draw, slide_num, total) + 24
    content_w = CANVAS_W - 2 * PAD

    f_sec = _f("arialbd.ttf", 38)
    label = f"{emoji}  {section_title.upper()}" if emoji else section_title.upper()
    draw.text((PAD, y), label, font=f_sec, fill=BLUE)
    y += 50

    uw = min(draw.textbbox((0, 0), label, font=f_sec)[2], 200)
    draw.rectangle([(PAD, y), (PAD + uw, y + 4)], fill=BLUE)
    y += 22

    f_body   = _f("arialbd.ttf", 30)
    f_detail = _f("arial.ttf",   26)
    f_num    = _f("ariblk.ttf",  38)

    shown = points[:4]
    avail_h = CANVAS_H - 72 - y - 16
    card_h  = min(128, (avail_h - (len(shown) - 1) * 10) // max(len(shown), 1))

    for i, point in enumerate(shown):
        if " — " in point:
            head, detail = point.split(" — ", 1)
        elif ": " in point and len(point.split(": ", 1)[0]) < 45:
            head, detail = point.split(": ", 1)
        else:
            head, detail = point, ""

        cy = y + i * (card_h + 10)
        draw.rounded_rectangle([(PAD, cy), (CANVAS_W - PAD, cy + card_h)], radius=14, fill=CARD_BG)
        draw.rounded_rectangle([(PAD, cy), (PAD + 7, cy + card_h)], radius=14, fill=BLUE)

        ncx, ncy, r = PAD + 46, cy + card_h // 2, 26
        draw.ellipse([(ncx - r, ncy - r), (ncx + r, ncy + r)], fill=BLUE)
        ns = str(i + 1)
        nw = draw.textbbox((0, 0), ns, font=f_num)[2]
        draw.text((ncx - nw // 2, ncy - 22), ns, font=f_num, fill=WHITE)

        tx, tw = PAD + 86, content_w - 86
        if detail:
            h_lines = _wrap(head, f_body, draw, tw)[:1]
            d_lines = _wrap(detail, f_detail, draw, tw)[:2]
            th = len(h_lines) * 36 + len(d_lines) * 30
            ts = cy + (card_h - th) // 2
            for ln in h_lines:
                draw.text((tx, ts), ln, font=f_body, fill=WHITE)
                ts += 36
            for ln in d_lines:
                draw.text((tx, ts), ln, font=f_detail, fill=MUTED)
                ts += 30
        else:
            h_lines = _wrap(head, f_body, draw, tw)[:2]
            th = len(h_lines) * 38
            ts = cy + (card_h - th) // 2
            for ln in h_lines:
                draw.text((tx, ts), ln, font=f_body, fill=WHITE)
                ts += 38

    _bottom_bar(img, draw)
    return img


# ── Slide 4: CTA ─────────────────────────────────────────────────────────────

def _cta_slide(brief: dict, slide_num: int, total: int) -> Image.Image:
    img, draw = _canvas()
    draw.rectangle([(0, 0), (CANVAS_W, 8)], fill=BLUE)
    draw.ellipse([(-100, CANVAS_H - 320), (260, CANVAS_H + 60)], fill=DARK_BLUE)
    draw.ellipse([(CANVAS_W - 200, -80), (CANVAS_W + 80, 220)], fill=DARK_BLUE)

    f_brand = _f("arialbd.ttf", 24)
    draw.text((PAD, 20), "THE TECH TUTORS", font=f_brand, fill=BLUE)
    counter = f"{slide_num} / {total}"
    cw = draw.textbbox((0, 0), counter, font=f_brand)[2]
    draw.text((CANVAS_W - PAD - cw, 20), counter, font=f_brand, fill=MUTED)

    content_w = CANVAS_W - 2 * PAD
    cy = CANVAS_H // 2 - 90

    f_save = _f("ariblk.ttf", 64)
    save_txt = "SAVE THIS POST"
    sw = draw.textbbox((0, 0), save_txt, font=f_save)[2]
    draw.text(((CANVAS_W - sw) // 2 + 3, cy + 3), save_txt, font=f_save, fill=(5, 15, 30))
    draw.text(((CANVAS_W - sw) // 2, cy), save_txt, font=f_save, fill=WHITE)
    cy += 84

    f_em = _f("arialbd.ttf", 36)
    em = "\U0001f516  and share with a business owner"
    ew = draw.textbbox((0, 0), em, font=f_em)[2]
    draw.text(((CANVAS_W - ew) // 2, cy), em, font=f_em, fill=MUTED)
    cy += 58

    draw.rectangle([(CANVAS_W // 2 - 80, cy), (CANVAS_W // 2 + 80, cy + 4)], fill=BLUE)
    cy += 28

    f_follow = _f("arialbd.ttf", 34)
    follow = "Follow The Tech Tutors for weekly AI tips"
    fw = draw.textbbox((0, 0), follow, font=f_follow)[2]
    draw.text(((CANVAS_W - fw) // 2, cy), follow, font=f_follow, fill=BLUE_LT)
    cy += 54

    cta_text = brief.get("cta_text", "We build custom AI tools for your business.")
    f_cta = _f("arial.ttf", 27)
    for line in _wrap(cta_text, f_cta, draw, content_w)[:3]:
        lw = draw.textbbox((0, 0), line, font=f_cta)[2]
        draw.text(((CANVAS_W - lw) // 2, cy), line, font=f_cta, fill=MUTED)
        cy += 36

    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((60, 60))
            img.paste(logo, ((CANVAS_W - 60) // 2, CANVAS_H - 138), logo)
        except Exception:
            pass

    draw.rectangle([(0, CANVAS_H - 52), (CANVAS_W, CANVAS_H)], fill=(8, 18, 30))
    f_site = _f("arialbd.ttf", 24)
    site = "the-tech-tutors.vercel.app"
    sw2 = draw.textbbox((0, 0), site, font=f_site)[2]
    draw.text(((CANVAS_W - sw2) // 2, CANVAS_H - 42), site, font=f_site, fill=BLUE)

    return img


# ── Split helper ──────────────────────────────────────────────────────────────

def _split(points: list, n: int) -> list[list]:
    size = max(1, len(points) // n)
    result = []
    for i in range(n):
        start = i * size
        end = start + size if i < n - 1 else len(points)
        result.append(points[start:end])
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def generate_slide_deck(brief: dict, date_str: str) -> tuple[str, str]:
    """Generate multi-slide PDF. Returns (pdf_path, preview_png_path)."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    template = brief.get("template", "list")
    points   = brief.get("graphic_points", [])
    total    = 3 if template == "stat" else 4

    slides = [_hook_slide(brief, 1, total)]

    if template == "stat":
        slides.append(_content_slide(points[:4], "What This Means For You", 2, total, "\U0001f4ca"))
    elif template == "steps":
        parts = _split(points, 2)
        slides.append(_content_slide(parts[0], "The Steps", 2, total, "\U0001f4cb"))
        slides.append(_content_slide(parts[1], "Continued", 3, total, "✅"))
    elif template == "comparison":
        half = len(points) // 2
        slides.append(_content_slide(points[:half], "The Old Way", 2, total, "❌"))
        slides.append(_content_slide(points[half:], "The New Way", 3, total, "✅"))
    else:
        parts = _split(points, 2)
        slides.append(_content_slide(parts[0], "The Tools", 2, total, "\U0001f527"))
        slides.append(_content_slide(parts[1], "More Tools", 3, total, "⚡"))

    slides.append(_cta_slide(brief, total, total))

    pdf_path     = str(OUTPUT_DIR / f"{date_str}_carousel.pdf")
    preview_path = str(OUTPUT_DIR / f"{date_str}_slide1.png")

    slides[0].save(pdf_path, save_all=True, append_images=slides[1:])
    slides[0].save(preview_path, "PNG")

    print(f"  [designer] {len(slides)} slides -> {pdf_path}")
    return pdf_path, preview_path


def generate_graphic(brief: dict, date_str: str) -> str:
    """Backward-compatible wrapper — returns preview PNG path."""
    _, preview = generate_slide_deck(brief, date_str)
    return preview


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
    content_w = CANVAS_W - 2 * PAD
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


def generate_research_pdf(report: dict, date_str: str, source_url: str = "") -> str:
    """Generate a branded 2-3 page research PDF. Returns PDF path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        HRFlowable, Table, TableStyle,
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    pdf_path = str(OUTPUT_DIR / f"{date_str}_research.pdf")

    NAVY  = HexColor("#0D1B2A")
    BLUE  = HexColor("#0EA5E9")
    MUTED = HexColor("#64748B")
    CARD  = HexColor("#EFF6FF")

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=1.5*cm, bottomMargin=2*cm,
    )

    S = {}
    for name, kwargs in [
        ("brand",    dict(fontSize=9,  textColor=white,  fontName="Helvetica-Bold")),
        ("date_r",   dict(fontSize=9,  textColor=MUTED,  alignment=TA_RIGHT)),
        ("headline", dict(fontSize=20, textColor=NAVY,   fontName="Helvetica-Bold", leading=26, spaceBefore=14, spaceAfter=10)),
        ("section",  dict(fontSize=11, textColor=BLUE,   fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=5)),
        ("body",     dict(fontSize=10, textColor=NAVY,   leading=16, spaceAfter=6)),
        ("bullet",   dict(fontSize=10, textColor=NAVY,   leading=16, spaceAfter=5, leftIndent=14)),
        ("takeaway", dict(fontSize=11, textColor=NAVY,   fontName="Helvetica-Bold", leading=18, leftIndent=10, rightIndent=10, spaceBefore=6, spaceAfter=6)),
        ("footer",   dict(fontSize=8,  textColor=MUTED,  alignment=TA_CENTER)),
    ]:
        S[name] = ParagraphStyle(name, **kwargs)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table(
        [[Paragraph("THE TECH TUTORS — AI Research Brief", S["brand"]),
          Paragraph(date_str, S["date_r"])]],
        colWidths=["70%", "30%"],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0,  -1), 14),
        ("RIGHTPADDING",  (1, 0), (1,  -1), 14),
        ("LINEBELOW",     (0, -1), (-1, -1), 3, BLUE),
    ]))
    story.append(hdr)

    # ── Headline ──────────────────────────────────────────────────────────────
    story.append(Paragraph(report.get("headline", ""), S["headline"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=10))

    # ── Executive Summary ─────────────────────────────────────────────────────
    story.append(Paragraph("EXECUTIVE SUMMARY", S["section"]))
    story.append(Paragraph(report.get("executive_summary", ""), S["body"]))

    # ── Key Findings ──────────────────────────────────────────────────────────
    story.append(Paragraph("KEY FINDINGS", S["section"]))
    for finding in report.get("key_findings", []):
        story.append(Paragraph("&#x2022;  " + finding, S["bullet"]))

    story.append(Spacer(1, 8))

    # ── Business Impact ───────────────────────────────────────────────────────
    story.append(Paragraph("WHAT THIS MEANS FOR YOUR BUSINESS", S["section"]))
    for impact in report.get("business_impact", []):
        story.append(Paragraph("&#x2022;  " + impact, S["bullet"]))

    story.append(Spacer(1, 8))

    # ── The Tech Tutors' Take ─────────────────────────────────────────────────
    story.append(Paragraph("THE TECH TUTORS' TAKE", S["section"]))
    story.append(Paragraph(report.get("tech_tutors_take", ""), S["body"]))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=BLUE))
    story.append(Spacer(1, 8))

    # ── Key Takeaway (highlighted) ────────────────────────────────────────────
    story.append(Paragraph("KEY TAKEAWAY", S["section"]))
    takeaway_box = Table(
        [[Paragraph(report.get("key_takeaway", ""), S["takeaway"])]],
        colWidths=["100%"],
    )
    takeaway_box.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CARD),
        ("LINEAFTER",     (0, 0), (0,  -1), 3, BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
        ("ROUNDEDCORNERS", [6]),
    ]))
    story.append(takeaway_box)

    # ── Sources ───────────────────────────────────────────────────────────────
    if source_url:
        story.append(Spacer(1, 14))
        story.append(Paragraph("SOURCE", S["section"]))
        story.append(Paragraph(source_url, S["body"]))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MUTED))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "The Tech Tutors &nbsp;|&nbsp; AI Tools &amp; Automations for Businesses "
        "&nbsp;|&nbsp; the-tech-tutors.vercel.app",
        S["footer"],
    ))

    doc.build(story)
    print(f"  [designer] Research PDF -> {pdf_path}")
    return pdf_path
