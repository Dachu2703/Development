"""Resolution-aware Tamil Shorts title rendering."""

from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont


PRESETS = {
    "NEWS": {"normal": "#FFFFFF", "highlight": "#FFD600", "critical": "#FF2B2B"},
    "POLITICS": {"normal": "#FFFFFF", "highlight": "#FFD600", "critical": "#FF2B2B"},
    "ASTROLOGY": {"normal": "#FFFFFF", "highlight": "#FFD600", "critical": "#FFB300"},
    "MOTIVATION": {"normal": "#FFFFFF", "highlight": "#FFD600", "critical": "#FF2B2B"},
}

KEYWORDS = {
    "விஜய்", "அதிரடி", "முடிவு", "கூட்டணி", "தேர்தல்", "அரசியல்",
    "திட்டம்", "மிகப்பெரிய", "பயங்கர", "சோதனை", "ஜோதிடம்", "பொய்",
}
CRITICAL_WORDS = {"பயங்கர", "மிகப்பெரிய", "அதிரடி", "சோதனை"}


def _font_path(requested: str | None = None) -> str:
    candidates = [requested] if requested else []
    candidates += [
        "C:/Windows/Fonts/NotoSansTamil-ExtraBold.ttf",
        "C:/Windows/Fonts/NotoSansTamil-Bold.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/Nirmala.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansTamil-ExtraBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansTamil-Bold.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise FileNotFoundError(
        "A Tamil font is required. Upload Noto Sans Tamil ExtraBold/Bold in the UI."
    )


def _words(title: str) -> List[str]:
    return [word for word in title.strip().split() if word]


def _highlight(word: str, preset: Dict) -> str:
    clean = word.strip(".,!?;:()[]")
    if clean in CRITICAL_WORDS:
        return preset["critical"]
    if clean in KEYWORDS:
        return preset["highlight"]
    return preset["normal"]


def _line_candidates(words: List[str], font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _balanced_lines(words: List[str], font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> List[str]:
    lines = _line_candidates(words, font, max_width)
    if len(lines) <= max_lines:
        return lines
    for split in range(1, len(words)):
        candidate = [" ".join(words[:split]), " ".join(words[split:])]
        if max(font.getlength(line) for line in candidate) <= max_width:
            return candidate
    return lines


def _fit_title(title: str, font_path: str, width: int, height: int, scale: float) -> Tuple[ImageFont.FreeTypeFont, List[str], int, int]:
    safe_width = max(1, int(width * 0.90))
    max_text_height = max(1, int(height * 0.80))
    words = _words(title)
    start_size = int((120 if len(title) < 24 else 100 if len(title) < 45 else 78) * scale)
    for size in range(max(start_size, 24), max(24, int(42 * scale)) - 1, -2):
        font = ImageFont.truetype(font_path, size=size)
        lines = _balanced_lines(words, font, safe_width, 3)
        line_height = max(font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines) if lines else size
        total_height = int(line_height * len(lines) * 1.02)
        max_line_width = max((font.getlength(line) for line in lines), default=0)
        if max_line_width <= safe_width and total_height <= max_text_height:
            stroke = max(4, min(12, round(size / 10)))
            return font, lines, stroke, int(line_height * 1.02)
    font = ImageFont.truetype(font_path, size=max(24, int(42 * scale)))
    lines = _balanced_lines(words, font, safe_width, 3)
    return font, lines[:3], max(4, min(8, round(font.size / 10))), int(font.size * 1.02)


def renderShortsTitle(title: str, options: Dict | None = None) -> Image.Image:
    """Render a transparent, shaped Tamil title layer for FFmpeg composition."""
    options = options or {}
    width = int(options.get("videoWidth", 1080))
    height = int(options.get("videoHeight", 420))
    scale = width / 1080.0
    font_path = _font_path(options.get("fontPath"))
    preset = PRESETS.get(str(options.get("style", "NEWS")).upper(), PRESETS["NEWS"])
    font, lines, stroke, line_height = _fit_title(title, font_path, width, height, scale)
    shadow = max(2, round(3 * scale))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    total_height = line_height * len(lines)
    position = str(options.get("position", "center")).lower()
    if position == "top":
        y = max(40, int(height * 0.08))
    elif position == "bottom":
        y = max(40, height - total_height - int(height * 0.08))
    else:
        y = max(40, (height - total_height) // 2)
    for line in lines:
        tokens = line.split(" ")
        widths = [draw.textlength(token, font=font) for token in tokens]
        spaces = draw.textlength(" ", font=font)
        line_width = sum(widths) + spaces * max(0, len(tokens) - 1)
        x = max(int(40 * scale), int((width - line_width) / 2))
        for token, token_width in zip(tokens, widths):
            color = _highlight(token, preset)
            draw.text((x + shadow, y + shadow), token, font=font, fill=(0, 0, 0, 165), stroke_width=stroke, stroke_fill=(0, 0, 0, 165))
            draw.text((x, y), token, font=font, fill=color, stroke_width=stroke, stroke_fill="#000000")
            x += int(token_width + spaces)
        y += line_height
    return image


def render_shorts_title(title: str, output_path: str, options: Dict | None = None) -> str:
    image = renderShortsTitle(title, options)
    image.save(output_path, "PNG")
    return output_path
