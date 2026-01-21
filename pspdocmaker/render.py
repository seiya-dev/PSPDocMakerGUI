from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple, Optional, Iterable
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .font_resolver import load_font
from .utils import get_w

@dataclass
class RenderSettings:
    page_w: int = 480
    page_h: int = 272
    
    margin_left:   int = 16
    margin_top:    int = 16
    margin_right:  int = 16
    margin_bottom: int = 16
    
    font_path:  Optional[str] = None
    font_size:  int = 14
    font_color: Tuple[int, int, int] = (255, 255, 255)
    
    word_wrap:         bool = True
    line_spacing:      int = 4
    indent_first_line: int = 0
    
    background_mode:       str = 'solid'
    bg_color:              Tuple[int, int, int] = (0, 0, 0)
    grad_start:            Tuple[int, int, int] = (10, 10, 10)
    grad_end:              Tuple[int, int, int] = (70, 70, 70)
    frame_color:           Tuple[int, int, int] = (255, 255, 255)
    frame_thickness:       int = 5
    invert:                bool = False
    random_style_gradient: bool = False
    random_style_frame:    bool = False
    
    background_image: Optional[str] = None

@lru_cache(maxsize=64)
def _cached_gradient(w: int, h: int, c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    
    mask = Image.linear_gradient('L').resize((1, h))
    
    r = Image.eval(mask, lambda t: int(c1[0] + (c2[0] - c1[0]) * t / 255))
    g = Image.eval(mask, lambda t: int(c1[1] + (c2[1] - c1[1]) * t / 255))
    b = Image.eval(mask, lambda t: int(c1[2] + (c2[2] - c1[2]) * t / 255))
    
    grad = Image.merge('RGB', (r, g, b))
    return grad.resize((w, h), Image.Resampling.BILINEAR)


def make_background(rs: RenderSettings, page_index: int = 0) -> Image.Image:
    w, h = rs.page_w, rs.page_h
    grad_start, grad_end = rs.grad_start, rs.grad_end
    frame_color = rs.frame_color
    
    # --- random styles ---
    if rs.random_style_gradient:
        rng = random.Random(100000 + page_index)
        grad_start = (
            rng.randrange(256),
            rng.randrange(256),
            rng.randrange(256),
        )
        grad_end = (
            rng.randrange(256),
            rng.randrange(256),
            rng.randrange(256),
        )
    
    if rs.random_style_frame:
        rng = random.Random(200000 + page_index)
        frame_color = (
            rng.randrange(256),
            rng.randrange(256),
            rng.randrange(256),
        )
    
    # --- background base ---
    if rs.background_image:
        try:
            base = (
                Image.open(rs.background_image)
                .convert('RGB')
                .resize((w, h), Image.Resampling.LANCZOS)
            )
        except Exception:
            base = Image.new('RGB', (w, h), rs.bg_color)
    
    elif rs.background_mode == 'solid':
        base = Image.new('RGB', (w, h), rs.bg_color)
    
    elif rs.background_mode == 'gradient':
        base = _cached_gradient(
            w, h,
            grad_start,
            grad_end
        ).copy()
    
    else:
        # fallback
        base = Image.new('RGB', (w, h), rs.bg_color)
    
    # --- frame ---
    if rs.background_mode == 'frame':
        draw = ImageDraw.Draw(base)
        t = clamp(rs.frame_thickness, 1, 50)
        for i in range(t):
            draw.rectangle(
                [i, i, w - 1 - i, h - 1 - i],
                outline=frame_color
            )
    
    # --- invert ---
    if rs.invert:
        base = ImageOps.invert(base)
    
    return base

def split_text_to_lines(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int, rs: RenderSettings) -> List[str]:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines_out = []
    for raw_line in text.split('\n'):
        if raw_line == '':
            lines_out.append('')
            continue
        if not rs.word_wrap:
            buf = ''
            for ch in raw_line:
                cand = buf + ch
                # w = draw.textlength(cand, font=font)
                w = get_w(cand, draw, font)
                if w <= max_width or buf == '':
                    buf = cand
                else:
                    lines_out.append(buf)
                    buf = ch
            if buf:
                lines_out.append(buf)
            continue
        
        words = re.split(r'(\s+)', raw_line)
        cur = ''
        for tok in words:
            cand = cur + tok
            # w = draw.textlength(cand, font=font)
            w = get_w(cand, draw, font)
            if w <= max_width or cur == '':
                cur = cand
            else:
                lines_out.append(cur.rstrip('\n'))
                cur = tok.lstrip()
        if cur != '':
            lines_out.append(cur.rstrip('\n'))
    return lines_out

def render_text_to_pages(text: str, rs: RenderSettings, start_page_index: int = 0) -> List[Image.Image]:
    PAGEBREAK_TOKEN = '<<PAGEBREAK>>'
    INLINE_PB = '@pb@'
    font = load_font(rs.font_path, rs.font_size)
    
    parts: List[str] = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if INLINE_PB in line:
            segs = line.split(INLINE_PB)
            for i, seg in enumerate(segs):
                if seg != '': parts.append(seg)
                if i != len(segs) - 1: parts.append('\n'+PAGEBREAK_TOKEN+'\n')
        else:
            parts.append(line)
        parts.append('\n')
    norm = ''.join(parts)
    
    max_text_w = rs.page_w - rs.margin_left - rs.margin_right
    max_text_h = rs.page_h - rs.margin_top - rs.margin_bottom
    ascent, descent = font.getmetrics()
    base_line_h = ascent + descent + rs.line_spacing
    
    pages = []
    cur_page_index = start_page_index
    cur_img = make_background(rs, page_index=cur_page_index)
    draw = ImageDraw.Draw(cur_img)
    x0 = rs.margin_left
    y = rs.margin_top
    
    def new_page():
        nonlocal cur_img, draw, y, cur_page_index
        pages.append(cur_img)
        cur_page_index += 1
        cur_img = make_background(rs, page_index=cur_page_index)
        draw = ImageDraw.Draw(cur_img)
        y = rs.margin_top
    
    chunks = norm.split('\n')
    for raw in chunks:
        if raw == PAGEBREAK_TOKEN:
            new_page()
            continue
        if raw == '':
            y += base_line_h
            if y + base_line_h > rs.margin_top + max_text_h:
                new_page()
            continue
        
        wrapped = split_text_to_lines(raw, draw, font, max_text_w - rs.indent_first_line, rs)
        for li, line in enumerate(wrapped):
            if line == '' and li == 0:
                y += base_line_h
                continue
            indent = rs.indent_first_line if li == 0 else 0
            draw.text((x0 + indent, y), line, font=font, fill=rs.font_color)
            y += base_line_h
            if y + base_line_h > rs.margin_top + max_text_h:
                new_page()
    pages.append(cur_img)
    return pages

def render_image_to_page(img_path: Path, rs: RenderSettings, for_file: bool = False, page_index: int = 0) -> Image.Image:
    base = make_background(rs, page_index=page_index)
    
    try:
        img = Image.open(img_path).convert('RGBA')
    except Exception:
        draw = ImageDraw.Draw(base)
        draw.text((10, 10), f'Failed to open:\n{img_path.name}', fill=(255, 0, 0))
        return base
    
    img.thumbnail(
        (rs.page_w, rs.page_h),
        Image.Resampling.LANCZOS
    )
    
    bw, bh = rs.page_w, rs.page_h
    iw, ih = img.size
    
    x = (bw - iw) // 2
    y = (bh - ih) // 2
    
    if not for_file:
        base_rgba = base.convert('RGBA')
        base_rgba.alpha_composite(img, (x, y))
        return base_rgba.convert('RGB')
    else:
        return img
