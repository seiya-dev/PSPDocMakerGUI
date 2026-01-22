# coding: utf-8

from typing import List, Tuple, Optional, Iterable
import sys

from PIL import ImageFont
import wx

class FontResolver:
    # Resolve wx.Font to a real font file path in a cross-platform way.
    
    def resolve(self, wx_font: wx.Font) -> Optional[str]:
        if sys.platform.startswith('win'):
            return self._resolve_windows(wx_font)
        else:
            return self._resolve_linux(wx_font)
    
    # ---------------- Windows ----------------
    
    def _resolve_windows(self, wx_font: wx.Font) -> Optional[str]:
        try:
            import winreg
        except ImportError:
            return None
        
        face = wx_font.GetFaceName()
        if not face or face.startswith('@'):
            return None
        
        want_bold = wx_font.GetWeight() >= wx.FONTWEIGHT_BOLD
        want_italic = wx_font.GetStyle() in (
            wx.FONTSTYLE_ITALIC,
            wx.FONTSTYLE_SLANT,
        )
        
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts',
            ) as key:
            
                best_match = None
                
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, value, _ = winreg.EnumValue(key, i)
                    
                    name_l = name.lower()
                    face_l = face.lower()
                    
                    if face_l not in name_l:
                        continue
                    
                    is_bold = 'bold' in name_l
                    is_italic = 'italic' in name_l or 'oblique' in name_l
                    
                    # exact style match
                    if is_bold == want_bold and is_italic == want_italic:
                        best_match = value
                        break
                    
                    # fallback: regular
                    if best_match is None and not is_bold and not is_italic:
                        best_match = value
                
                if best_match:
                    fonts_dir = Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'Fonts'
                    return str(fonts_dir / best_match)
        
        except Exception:
            return None
        
        return None
    
    # ---------------- Linux ----------------
    
    def _resolve_linux(self, wx_font: wx.Font) -> Optional[str]:
        family = wx_font.GetFaceName()
        if not family:
            return None
        
        pattern_parts = [family]
        
        if wx_font.GetWeight() >= wx.FONTWEIGHT_BOLD:
            pattern_parts.append('weight=bold')
        
        if wx_font.GetStyle() in (wx.FONTSTYLE_ITALIC, wx.FONTSTYLE_SLANT):
            pattern_parts.append('slant=italic')
        
        size = wx_font.GetPointSize()
        if size > 0:
            pattern_parts.append(f'size={size}')
        
        pattern = ':'.join(pattern_parts)
        
        try:
            proc = subprocess.run(
                ['fc-match', '-f', '%{file}', pattern],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=True,
            )
            path = proc.stdout.strip()
            if path and Path(path).exists():
                return path
        except Exception:
            return None
        
        return None

def load_font(font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    if not font_path:
        raise ValueError('Font path is not set')
    
    try:
        return ImageFont.truetype(font_path, size)
    except Exception as e:
        raise RuntimeError(f'Failed to load font:\n{font_path}\n{e}')
