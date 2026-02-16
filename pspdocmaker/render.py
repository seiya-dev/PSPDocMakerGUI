# coding: utf-8

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple, Optional, Iterable
from pathlib import Path
import random
import re

import wx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .font_resolver import load_font
from .utils import get_w, clamp

@dataclass
class RenderSettings:
    page_w: int = 480
    page_h: int = 480
    
    max_w: int = 480
    max_h: int = 480
    
    panel_w: int = 480
    panel_h: int = 480
    
    font_path: Optional[str] = None
    font_size: int = 12
    
    font_color: Tuple[int, int, int] = (255, 255, 255)
    
    word_wrap: bool = True
    
    margin_left:       int = 14
    margin_top:        int = 14
    margin_right:      int = 14
    margin_bottom:     int = 14
    
    line_spacing:      int = 1
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

class ExtraRenderParamsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title='Set Extra Parameters:', style=wx.DEFAULT_DIALOG_STYLE)
        rs = RenderSettings
        
        extra_params = {
            # margins
            'top':    rs.margin_top,
            'left':   rs.margin_left,
            'right':  rs.margin_right,
            'bottom': rs.margin_bottom,
            # spacing
            'line_spacing': rs.line_spacing,
            'indent_first': rs.indent_first_line,
        }
        
        grid = wx.FlexGridSizer(rows=6, cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1, 1)
        
        def add_row(label, key, vmin, vmax):
            grid.Add(wx.StaticText(self, label=label + ':'), 0, wx.ALIGN_CENTER_VERTICAL)
            sc = wx.SpinCtrl(self, min=vmin, max=vmax, initial=int(extra_params.get(key, 0)))
            grid.Add(sc, 0, wx.EXPAND)
            return sc
        
        self.sc_top = add_row('Top', 'top', 0, 50)
        self.sc_left = add_row('Left', 'left', 0, 50)
        self.sc_right = add_row('Right', 'right', 0, 50)
        self.sc_bottom = add_row('Bottom', 'bottom', 0, 50)
        
        self.sc_line_spacing = add_row('Line Spacing', 'line_spacing', 0, 10)
        self.sc_indent_first = add_row('Indent First Line', 'indent_first', 0, 50)
        
        btns = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
        s.Add(btns, 0, wx.ALL | wx.EXPAND, 12)
        
        self.SetSizerAndFit(s)
        self.CentreOnParent()

    def set_extra_params(self):
        rs = RenderSettings
        
        rs.margin_top    = self.sc_top.GetValue()
        rs.margin_left   = self.sc_left.GetValue()
        rs.margin_right  = self.sc_right.GetValue()
        rs.margin_bottom = self.sc_bottom.GetValue()
        
        rs.line_spacing      = self.sc_line_spacing.GetValue()
        rs.indent_first_line = self.sc_indent_first.GetValue()

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
    
    ml = rs.margin_left
    mr = rs.margin_right
    mt = rs.margin_top
    mb = rs.margin_bottom
    
    frame_pad = rs.frame_thickness if rs.background_mode == 'frame' else 0
    ml_eff = ml + frame_pad
    mr_eff = mr + frame_pad
    mt_eff = mt + frame_pad
    mb_eff = mb + frame_pad
    
    max_text_w = rs.page_w - ml_eff - mr_eff
    max_text_h = rs.page_h - mt_eff - mb_eff
    
    max_text_w = max(50, min(rs.page_w, max_text_w))
    max_text_h = max(50, min(rs.page_h, max_text_h))
    
    ascent, descent = font.getmetrics()
    base_line_h = ascent + descent + rs.line_spacing
    
    pages = []
    cur_page_index = start_page_index
    cur_img = make_background(rs, page_index=cur_page_index)
    draw = ImageDraw.Draw(cur_img)
    
    x0 = ml_eff
    y = mt_eff
    
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
        img = Image.open(img_path)
    except Exception:
        draw = ImageDraw.Draw(base)
        draw.text((10, 10), f'Failed to open:\n{img_path.name}', fill=(255, 0, 0))
        return base
    
    if img.mode not in {'RGB', 'RGBA', 'L', 'LA'}:
        img = img.convert('RGBA')
    
    iw, ih = img.size
    if iw > rs.max_w or ih > rs.max_h:
        img.thumbnail(
            (rs.max_w, rs.max_h),
            Image.Resampling.LANCZOS
        )
    
    if for_file:
        return img
    
    bw, bh = rs.panel_w, rs.panel_h
    iw, ih = img.size
    
    scale = min(bw / iw, bh / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    
    img = img.convert('RGB')
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    
    x = (bw - nw) // 2
    y = (bh - nh) // 2
    
    base = Image.new('RGBA', (bw, bh), (0, 0, 0, 255))
    base.alpha_composite(img.convert('RGBA'), (x, y))
    return base.convert('RGB')
