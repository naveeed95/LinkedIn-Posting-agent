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

# ── Colors ───────────────────────────────────────────────────────────────────
BG_TOP    = (13,  27,  42)
BG_BOT    = (20,  42,  68)
BLUE      = (14,  165, 233)
BLUE_LT   = (56,  189, 248)
WHITE     = (255, 255, 255)
MUTED     = (148, 163, 184)
CARD_BG   = (22,  48,  80)
DARK_LINE = (35,  65,  100)
DARK_BLUE = (10,  80,  140)

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


def _top_bar(draw: ImageDraw.ImageDraw, slide_num: int, total: int) -> int:
    draw.rectangle([(0, 0), (CANVAS_W, 7)], fill=BLUE)
    f = _f("arialbd.ttf", 23)
    draw.text((PAD, 20), "THE TECH TUTORS", font=f, fill=BLUE)
    counter = f"{slide_num} / {total}"
    cw = draw.textbbox((0, 0), counter, font=f)[2]
    draw.text((CANVAS_W - PAD - cw, 20), counter, font=f, fill=MUTED)
    return 72


def _bottom_bar(img: Image.Image, draw: ImageDraw.ImageDraw):
    bar_y = CANVAS_H - 72
    draw.rectangle([(0, bar_y), (CANVAS_W, CANVAS_H)], fill=(10, 22, 36))
    draw.rectangle([(0, bar_y), (CANVAS_W, bar_y + 2)], fill=BLUE)
    f = _f("arial.ttf", 22)
    tx = PAD
    if LOGO_PATH.exists():
        try:
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((44, 44))
            img.paste(logo, (PAD, bar_y + 14), logo)
            tx = PAD + 56
        except Exception:
            pass
    draw.text((tx, bar_y + 22), "AI Tools & Automations for Businesses", font=f, fill=MUTED)
    site = "the-tech-tutors.vercel.app"
    sw = draw.textbbox((0, 0), site, font=f)[2]
    draw.text((CANVAS_W - PAD - sw, bar_y + 22), site, font=f, fill=BLUE)


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

    print(f"  [designer] {len(slides)} slides → {pdf_path}")
    return pdf_path, preview_path


def generate_graphic(brief: dict, date_str: str) -> str:
    """Backward-compatible wrapper — returns preview PNG path."""
    _, preview = generate_slide_deck(brief, date_str)
    return preview
