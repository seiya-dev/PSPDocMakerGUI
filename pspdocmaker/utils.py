from typing import List, Tuple, Optional, Iterable
from pathlib import Path

import wx
from PIL import Image, ImageDraw, ImageFont, ImageOps

def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

def hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip()
    if h.startswith('#'):
        h = h[1:]
    if len(h) == 3:
        h = ''.join([c*2 for c in h])
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (255, 255, 255) # Fallback

def wx_col_to_hex(c: wx.Colour) -> str:
    return '#{:02x}{:02x}{:02x}'.format(c.Red(), c.Green(), c.Blue())

def detect_text_encoding(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except Exception:
        pass
    for enc in ('cp1252', 'cp1251', 'cp866', 'latin-1'):
        try:
            raw.decode(enc)
            return enc
        except Exception:
            continue
    return 'latin-1'

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def list_image_files(folder: Path) -> List[Path]:
    exts = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp'}
    out = []
    for f in sorted(folder.rglob('*')):
        if f.is_file() and f.suffix.lower() in exts:
            out.append(f)
    return out

def list_text_files(folder: Path) -> List[Path]:
    exts = {'.txt'}
    out = []
    for f in sorted(folder.rglob('*')):
        if f.is_file() and f.suffix.lower() in exts:
            out.append(f)
    return out

def is_dat_file(p: Path) -> bool:
    return p.suffix.lower() == '.dat'

width_cache: dict[tuple[str, int], float] = {}
def get_w(s, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont):
    key = (s, id(font))
    if key not in width_cache:
        width_cache[key] = draw.textlength(s, font=font)
    return width_cache[key]
