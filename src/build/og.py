"""Static sharing cards using the website's fonts and light-mode palette."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

ASSETS = Path("static/i")
WIDTH, HEIGHT = 1200, 630


@lru_cache
def _style() -> tuple[dict[str, str], bytes]:
    css = (ASSETS / "style.css").read_bytes()
    colors = dict(re.findall(r"--([\w-]+): light-dark\((#[\dA-Fa-f]+),", css.decode()))
    version = css + Path(__file__).read_bytes()
    for weight in ("Regular", "SemiBold"):
        version += (ASSETS / f"FiraSans-{weight}.woff2").read_bytes()
    version += (ASSETS / "favicon-32x32.png").read_bytes()
    return colors, hashlib.sha256(version).digest()


@lru_cache(maxsize=128)
def _font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f"FiraSans-{weight}.woff2"), size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ""
        # A single long word (for example a cinema name) must fit as well.
        for char in word:
            if line and font.getlength(line + char) > width:
                lines.append(line)
                line = ""
            line += char
    if line:
        lines.append(line)
    return lines


def write_card(
    out_dir: Path,
    *,
    title: str = "Alla biografer",
    subtitle: str = "Filmer och bioprogram i hela Sverige",
    poster: Path | None = None,
    year: int | None = None,
) -> str:
    """Write a content-addressed JPEG and return its site-relative URL.

    Posters are contained, never cropped. Missing or unreadable artwork produces
    a text-only card; the page's title and scope remain available when shared.
    """
    colors, version = _style()
    artwork = None
    if poster is not None:
        try:
            with Image.open(poster) as source:
                artwork = ImageOps.exif_transpose(source).convert("RGB")
        except (FileNotFoundError, UnidentifiedImageError, OSError):
            pass
    if year is not None:
        title = f"{title} {year}"
    digest = hashlib.sha256(version + json.dumps([title, subtitle], ensure_ascii=False).encode())
    if artwork is not None:
        digest.update(str(artwork.size).encode())
        digest.update(artwork.tobytes())
    url = f"/og/{digest.hexdigest()[:20]}.jpg"
    dest = out_dir / url.lstrip("/")
    if dest.exists():
        return url

    image = Image.new("RGB", (WIDTH, HEIGHT), colors["background"])
    draw = ImageDraw.Draw(image)
    with Image.open(ASSETS / "favicon-32x32.png") as source:
        icon = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        image.paste(icon, (56, 44), icon)
    draw.text((140, 52), "allabiografer.se", font=_font(56, "SemiBold"), fill=colors["text"], anchor="lt")
    left = 56
    width = 1088
    if artwork is not None:
        artwork = ImageOps.contain(artwork, (320, 518), Image.Resampling.LANCZOS)
        image.paste(artwork, (1144 - artwork.width, 56))
        width = 1144 - artwork.width - 48 - left
    subtitle_font = _font(52)
    subtitle_lines = _wrap(subtitle, subtitle_font, width)
    for size in range(112, 23, -2):
        title_font = _font(size, "SemiBold")
        title_lines = _wrap(title, title_font, width)
        line_height = round(size * 1.14)
        block_height = len(title_lines) * line_height + 32 + len(subtitle_lines) * 64
        if block_height <= 384:
            break
    else:
        raise ValueError(f"Sharing card title is too long: {title}")

    y = 190
    for line in title_lines:
        draw.text((left, y), line, font=title_font, fill=colors["text"], anchor="lt")
        y += line_height
    y += 32
    for line in subtitle_lines:
        draw.text((left, y), line, font=subtitle_font, fill=colors["text"], anchor="lt")
        y += 64

    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "JPEG", quality=90, subsampling=0, optimize=True)
    return url
