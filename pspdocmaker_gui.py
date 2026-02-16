#!/usr/bin/python3
#!/usr/bin/env python
# coding: utf-8

import os
import re
import sys
import shutil
import threading
import configparser

from pathlib import Path
from typing import List, Tuple, Optional, Iterable

# ---------------------------
# Dependencies
# ---------------------------

try:
    import wx
    import wx.lib.scrolledpanel
    from wx.lib.agw.floatspin import FloatSpin
except ImportError as e:
    raise SystemExit('This app requires wxPython. Install with: pip install wxpython') from e

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as e:
    raise SystemExit('This app requires Pillow. Install with: pip install pillow') from e

# ---------------------------
# User Modules
# ---------------------------

from pspdocmaker.font_resolver import FontResolver
from pspdocmaker.psp_docdat import POPS_VER_KEY, extract_pngs_from_dat, pack_pngs_to_dat, iter_png_blobs_from_dat

from pspdocmaker.render import (
    RenderSettings, _cached_gradient,
    make_background, render_image_to_page,
    split_text_to_lines, render_text_to_pages,
    ExtraRenderParamsDialog,
)

from pspdocmaker.utils import (
    rgb_to_hex, hex_to_rgb, wx_col_to_hex, detect_text_encoding,
    ensure_dir, list_image_files, list_text_files, is_dat_file,
    width_cache,
)

# ---------------------------
# Application
# ---------------------------

APP_NAME    = 'PSP DocMaker NX (GUI)'
CONFIG_FILE = 'pspdocmaker-config.ini'
GAMEID_PATTERN = re.compile(r"^[A-Za-z]{4}\d{5}$")

# ---------------------------
# UI: Main Application
# ---------------------------

class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(1000, 680))
        self.SetMinSize((1000, 680))
        
        self.panel = wx.Panel(self)
        
        self.key_bytes = POPS_VER_KEY
        
        self.base_dir = Path.cwd()
        self.temp_dir = self.base_dir / '_tmp_pages'
        
        self.inputs: List[Path] = []
        self.preview_pages: List[Path] = []
        self.preview_index = 0
        self.preview_bitmap = None
        
        self.doc_sizes = {
            0: ['480x248', '480x272', '480x480'],
            1: ['480x248', '480x272', '480x480', '480x960'],
        }
        
        self.doc_game_id = 'PSDM02025'
        self.cfg = configparser.ConfigParser()
        
        font = wx.Font(
            10,
            wx.FONTFAMILY_DEFAULT,
            wx.FONTSTYLE_NORMAL,
            wx.FONTWEIGHT_NORMAL
        )
        
        self.SetFont(font)
        self._init_ui()
        
        self._load_config()
        self._apply_config()
        
        self.font_resolver = FontResolver()
        self._ensure_default_font()
        
        self.Center()
    
    def _init_ui(self):
        main_win = wx.BoxSizer(wx.HORIZONTAL)
        
        # --- LEFT PANEL: Files ---
        left_panel = wx.BoxSizer(wx.VERTICAL)
        
        lbl_files = wx.StaticText(self.panel, label='FILES / FOLDERS')
        lbl_files.SetFont(lbl_files.GetFont().Bold())
        left_panel.Add(lbl_files, 0, wx.ALL, 5)
        
        self.lst_files = wx.ListBox(self.panel, style=wx.LB_EXTENDED | wx.LB_HSCROLL)
        self.lst_files.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self.on_preview_selected())
        left_panel.Add(self.lst_files, 1, wx.EXPAND | wx.BOTTOM, 5)
        
        # File Buttons
        btn_leftbox1 = wx.BoxSizer(wx.HORIZONTAL)
        btn_leftbox2 = wx.BoxSizer(wx.HORIZONTAL)
        
        self.btn_add_files  = wx.Button(self.panel, label='Add Files')
        self.btn_add_folder = wx.Button(self.panel, label='Add Folder')
        self.btn_remove     = wx.Button(self.panel, label='Remove')
        
        self.btn_up    = wx.Button(self.panel, label='Up')
        self.btn_down  = wx.Button(self.panel, label='Down')
        self.btn_clear = wx.Button(self.panel, label='Clear')
        
        btn_leftbox1.Add(self.btn_add_files,  1, wx.RIGHT, 5)
        btn_leftbox1.Add(self.btn_add_folder, 1, wx.RIGHT, 5)
        btn_leftbox1.Add(self.btn_remove,     1)
        
        btn_leftbox2.Add(self.btn_up,    1, wx.RIGHT, 5)
        btn_leftbox2.Add(self.btn_down,  1, wx.RIGHT, 5)
        btn_leftbox2.Add(self.btn_clear, 1)
        
        left_panel.Add(btn_leftbox1, 0, wx.EXPAND | wx.BOTTOM, 5)
        left_panel.Add(btn_leftbox2, 0, wx.EXPAND)
        
        # Bindings
        self.Bind(wx.EVT_BUTTON, self.on_add_files,          self.btn_add_files)
        self.Bind(wx.EVT_BUTTON, self.on_add_folder,         self.btn_add_folder)
        self.Bind(wx.EVT_BUTTON, self.on_remove,             self.btn_remove)
        self.Bind(wx.EVT_BUTTON, lambda e: self.on_move(-1), self.btn_up)
        self.Bind(wx.EVT_BUTTON, lambda e: self.on_move(1),  self.btn_down)
        self.Bind(wx.EVT_BUTTON, self.on_clear,              self.btn_clear)
        
        main_win.Add(left_panel, 1, wx.EXPAND | wx.TOP | wx.LEFT | wx.BOTTOM, 10)
        
        # --- RIGHT PANEL: Settings ---
        right_panel = wx.BoxSizer(wx.VERTICAL)
        right_panel.SetMinSize((540, -1))
        
        # --- Preview Panel ---
        self.preview_panel = wx.Panel(self.panel)
        self.preview_panel.SetBackgroundColour(wx.BLACK)
        self.preview_canvas = wx.StaticBitmap(self.preview_panel)
        
        pv_inner = wx.BoxSizer(wx.VERTICAL)
        pv_inner.AddStretchSpacer()
        pv_inner.Add(self.preview_canvas, 0, wx.ALIGN_CENTER)
        pv_inner.AddStretchSpacer()
        pv_sizer = wx.BoxSizer(wx.VERTICAL)
        pv_sizer.Add(pv_inner, 1, wx.EXPAND)
        self.preview_panel.SetSizer(pv_sizer)
        
        right_panel.Add(self.preview_panel, 1, wx.EXPAND | wx.ALL, 5)
        self.preview_panel.Bind(wx.EVT_SIZE, self._on_preview_resize)
        
        # Prev/Next
        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.btn_prev = wx.Button(self.panel, label='◀')
        self.btn_next = wx.Button(self.panel, label='▶')
        
        self.st_page = wx.StaticText(self.panel, label='EMPTY', style=wx.ALIGN_CENTER)
        
        nav_sizer.Add(self.btn_prev, 0, wx.LEFT | wx.RIGHT, 5)
        nav_sizer.Add(self.st_page, 1, wx.ALIGN_CENTER_VERTICAL)
        nav_sizer.Add(self.btn_next, 0, wx.LEFT | wx.RIGHT, 5)
        
        right_panel.Add(nav_sizer, 0, wx.EXPAND)
        
        self.btn_prev.Bind(wx.EVT_BUTTON, lambda e: self._preview_step(-1))
        self.btn_next.Bind(wx.EVT_BUTTON, lambda e: self._preview_step(+1))
        
        # General Options
        opts_block_gen = wx.StaticBoxSizer(wx.VERTICAL, self.panel, 'General Options')
        
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row3 = wx.BoxSizer(wx.HORIZONTAL)
        
        # Row 1: Format and KEYS
        st_format = wx.StaticText(self.panel, label='FORMAT:')
        self.doc_type      = wx.Choice(self.panel, choices=['PS1 on PSP/PS3', 'PSP & PS minis'])
        self.btn_keysbin   = wx.Button(self.panel, label='KEYS.BIN (?)')
        self.btn_keyreset  = wx.Button(self.panel, label='RESET KEY')
        
        st_gameid = wx.StaticText(self.panel, label='GameID:')
        self.btn_setgameid = wx.Button(self.panel, label=self.doc_game_id)
        
        row1.Add(st_format,          0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row1.Add(self.doc_type,      0, wx.RIGHT, 10)
        row1.Add(self.btn_keysbin,   0, wx.RIGHT, 5)
        row1.Add(self.btn_keyreset,  0, wx.RIGHT, 5)
        
        row1.AddStretchSpacer(1)
        row1.Add(st_gameid,          0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        row1.Add(self.btn_setgameid, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        
        self.doc_type.Bind(wx.EVT_CHOICE, self._on_doc_type_change)
        self.btn_keysbin.Bind(wx.EVT_BUTTON, self._open_keysbin)
        self.btn_keyreset.Bind(wx.EVT_BUTTON, self._reset_keysbin)
        self.btn_setgameid.Bind(wx.EVT_BUTTON, self.on_setgameid)
        
        self.doc_type.SetToolTip(
            'Manual Format:\n'
            '• PS1 Game (EBOOT.BIN)\n'
            '• PSP / PS Minis'
        )
        
        self.btn_keysbin.SetToolTip(
            'Open KEYS.BIN, required for official PS1 Manuals\n'
            '• Must be exactly 16 bytes\n'
            '• Binary format\n'
            '• No padding\n\n'
            'Current KEY:\n'
            f'{self.key_bytes.hex(' ').upper()}'
        )
        
        # Row 2: Size, Wrap, Merge, Keep
        st_size = wx.StaticText(self.panel, label='Size:')
        self.ch_size   = wx.Choice(self.panel, choices=[])
        self.chk_wrap  = wx.CheckBox(self.panel, label='Word Wrap')
        self.chk_merge = wx.CheckBox(self.panel, label='Merge all to one')
        self.chk_keep  = wx.CheckBox(self.panel, label='Keep temp PNGs')
        
        row2.Add(st_size,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row2.Add(self.ch_size,   0, wx.RIGHT, 15)
        row2.Add(self.chk_wrap,  0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row2.Add(self.chk_merge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row2.Add(self.chk_keep,  0, wx.ALIGN_CENTER_VERTICAL)
        
        self.ch_size.SetToolTip(
            'Converted Text2Image image size\n'
            'Not applied to images, they always max sized'
        )
        
        self.chk_wrap.SetToolTip(
            'Lines are wrapped across the screen by words\n'
            'Unchecked this if you have a specially prepared text file'
        )
        
        self.chk_merge.SetToolTip(
            'If checked: All files from the list are converted into one project.\n'
            'Otherwise only selected file(s) in the list will be converted'
        )
        
        self.chk_keep.SetToolTip(
            'Do not delete _tmp_pages folder after DOCUMENT.DAT creation'
        )
        
        # Row 3: Font Controls
        st_font_size        = wx.StaticText(self.panel, label='Font Size:')
        self.spn_font_size  = wx.SpinCtrl(self.panel, min=8, max=72)
        self.btn_font_path  = wx.Button(self.panel, label='Select Font...')
        self.btn_font_color = wx.Button(self.panel, label='Font Color')
        self.btn_set_extra = wx.Button(self.panel, label='Set extra parameters...')
        
        self.btn_set_extra.SetToolTip('Set first line indent, text margins and line spacing')
        
        row3.Add(st_font_size,        0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row3.Add(self.spn_font_size,  0, wx.RIGHT, 10)
        row3.Add(self.btn_font_path,  0, wx.RIGHT, 10)
        row3.Add(self.btn_font_color, 0, wx.RIGHT, 10)
        row3.Add(self.btn_set_extra, 0, wx.RIGHT, 0)
        
        self.btn_font_path.Bind(wx.EVT_BUTTON, self.on_pick_font)
        self.btn_font_color.Bind(wx.EVT_BUTTON, self.on_pick_font_color)
        self.btn_set_extra.Bind(wx.EVT_BUTTON, self._on_set_extra)
        
        # add rows
        opts_block_gen.Add(row1, 0, wx.EXPAND | wx.ALL, 5)
        opts_block_gen.Add(row2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        opts_block_gen.Add(row3, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # add block
        right_panel.Add(opts_block_gen, 0, wx.EXPAND | wx.ALL, 5)
        
        # Background Options
        opts_block_bg = wx.StaticBoxSizer(wx.VERTICAL, self.panel, 'Background Settings')
        
        row4 = wx.BoxSizer(wx.HORIZONTAL)
        row5 = wx.BoxSizer(wx.HORIZONTAL)
        row6 = wx.BoxSizer(wx.HORIZONTAL)
        
        # Row 4: Mode and Flags
        st_mode         = wx.StaticText(self.panel, label='Mode:')
        self.ch_bg_mode = wx.Choice(self.panel, choices=['solid', 'gradient', 'frame'])
        self.chk_invert = wx.CheckBox(self.panel, label='Invert Colors')
        self.chk_rand_grad = wx.CheckBox(self.panel, label='Rnd Gradient')
        self.chk_rand_frame = wx.CheckBox(self.panel, label='Rnd Frame')
        
        row4.Add(st_mode,             0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row4.Add(self.ch_bg_mode,     0, wx.RIGHT, 15)
        row4.Add(self.chk_invert,     0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row4.Add(self.chk_rand_grad,  0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row4.Add(self.chk_rand_frame, 0, wx.ALIGN_CENTER_VERTICAL)
        
        # Row 5: Color Pickers
        self.btn_bg_solid = wx.Button(self.panel, label='Solid Color')
        self.btn_bg_start = wx.Button(self.panel, label='Grad Start')
        self.btn_bg_end   = wx.Button(self.panel, label='Grad End')
        self.btn_bg_frame = wx.Button(self.panel, label='Frame Color')
        
        for btn in (self.btn_bg_solid, self.btn_bg_start, self.btn_bg_end, self.btn_bg_frame):
            row5.Add(btn, 1, wx.RIGHT, 5)
        
        self.btn_bg_solid.Bind(wx.EVT_BUTTON, self.on_pick_bg_color)
        self.btn_bg_start.Bind(wx.EVT_BUTTON, lambda e: self.on_pick_grad('start'))
        self.btn_bg_end.Bind(wx.EVT_BUTTON, lambda e: self.on_pick_grad('end'))
        self.btn_bg_frame.Bind(wx.EVT_BUTTON, self.on_pick_frame_color)
        
        # Row 6: Frame Thickness and Image
        st_frame_fickness = wx.StaticText(self.panel, label='Frame Thickness:')
        self.spn_frame_thick = wx.SpinCtrl(self.panel, min=1, max=50)
        self.btn_bg_img = wx.Button(self.panel, label='BG Image...')
        self.btn_clr_bg_img = wx.Button(self.panel, label='Clear BG Img')
        
        row6.Add(st_frame_fickness,    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        row6.Add(self.spn_frame_thick, 0, wx.RIGHT, 5)
        row6.Add(self.btn_bg_img,      0, wx.RIGHT, 5)
        row6.Add(self.btn_clr_bg_img,  0)
        
        self.btn_bg_img.Bind(wx.EVT_BUTTON, self.on_pick_bg_image)
        self.btn_clr_bg_img.Bind(wx.EVT_BUTTON, self.on_clear_bg_image)
        
        opts_block_bg.Add(row4, 0, wx.EXPAND | wx.ALL, 5)
        opts_block_bg.Add(row5, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        opts_block_bg.Add(row6, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        right_panel.Add(opts_block_bg, 0, wx.EXPAND | wx.ALL, 5)
        
        # Action Buttons
        row7 = wx.BoxSizer(wx.HORIZONTAL)
        
        self.btn_preview  = wx.Button(self.panel, label='Preview')
        self.btn_create   = wx.Button(self.panel, label='Create .DAT')
        self.btn_extract  = wx.Button(self.panel, label='Extract from .DAT')
        self.btn_save_cfg = wx.Button(self.panel, label='Save Settings')
        
        row7.Add(self.btn_preview,  1, wx.RIGHT, 5)
        row7.Add(self.btn_create,   1, wx.RIGHT, 5)
        row7.Add(self.btn_extract,  1, wx.RIGHT, 5)
        row7.Add(self.btn_save_cfg, 1)
        
        right_panel.Add(row7, 0, wx.EXPAND | wx.ALL, 5)
        
        self.btn_preview.Bind(wx.EVT_BUTTON, self.on_preview_all)
        self.btn_create.Bind(wx.EVT_BUTTON, self.on_create_dat)
        self.btn_extract.Bind(wx.EVT_BUTTON, self.on_extract_dat)
        self.btn_save_cfg.Bind(wx.EVT_BUTTON, self.on_save_settings)
        
        # Progress and Status
        self.gauge = wx.Gauge(self.panel, range=100)
        right_panel.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        self.st_status = wx.StaticText(self.panel, label='Ready')
        right_panel.Add(self.st_status, 0, wx.ALL, 5)
        
        main_win.Add(right_panel, 1, wx.EXPAND | wx.ALL, 5)
        self.panel.SetSizer(main_win)
    
    # ---------------------------
    # Config Logic
    # ---------------------------
    def _load_config(self):
        p = self.base_dir / CONFIG_FILE
        if p.exists():
            try:
                self.cfg.read(p, encoding='utf-8')
            except Exception:
                self.cfg.read(p)
        for sec in ('General', 'Font', 'Layout', 'Background', 'Output'):
            if sec not in self.cfg:
                self.cfg[sec] = {}
    
    def _save_config_file(self):
        p = self.base_dir / CONFIG_FILE
        try:
            with p.open('w', encoding='utf-8') as f:
                self.cfg.write(f)
        except Exception as e:
            wx.MessageBox(f'Failed to save config:\n{e}', 'Error', wx.ICON_ERROR)
    
    def get_int_clamped(self, section, option, default, min_v=None, max_v=None):
        try:
            v = self.cfg.getint(section, option, fallback=default)
        except (ValueError, configparser.Error):
            v = default
        
        if min_v is not None and v < min_v:
            v = min_v
        if max_v is not None and v > max_v:
            v = max_v
        return v
    
    def _apply_config(self):
        doc_type = self.get_int_clamped('Output', 'type', 0, 0, 1)
        
        self.doc_type.SetSelection(doc_type)
        self._apply_doc_type_ui(doc_type)
        
        doc_sizes = self.doc_sizes[doc_type]
        self.update_doc_sizes_widget(doc_type)
        sel_size = self.cfg['Output'].get('size', doc_sizes[0]).strip()
        self.update_doc_sizes_widget(doc_type, sel_size)
        
        self.chk_wrap.SetValue(self.cfg['Layout'].getboolean('word_wrap', fallback=True))
        self.chk_merge.SetValue(self.cfg['General'].getboolean('merge_files', fallback=False))
        self.chk_keep.SetValue(self.cfg['General'].getboolean('keep_temp', fallback=False))
        
        self.spn_font_size.SetValue(int(self.cfg['Font'].get('size', str(RenderSettings.font_size))))
        
        rs = RenderSettings
        rs.margin_top    = self.get_int_clamped('Layout', 'margin_top',    rs.margin_top   , 0, 50)
        rs.margin_left   = self.get_int_clamped('Layout', 'margin_left',   rs.margin_left  , 0, 50)
        rs.margin_right  = self.get_int_clamped('Layout', 'margin_right',  rs.margin_right , 0, 50)
        rs.margin_bottom = self.get_int_clamped('Layout', 'margin_bottom', rs.margin_bottom, 0, 50)
        rs.indent_first_line = self.get_int_clamped('Layout', 'indent', rs.indent_first_line, 0, 50)
        
        bg_mode = self.cfg['Background'].get('mode', RenderSettings.background_mode)
        idx = self.ch_bg_mode.FindString(bg_mode)
        self.ch_bg_mode.SetSelection(idx if idx != wx.NOT_FOUND else 0)
        
        self.chk_invert.SetValue(self.cfg['Background'].getboolean('invert', fallback=False))
        self.chk_rand_grad.SetValue(self.cfg['Background'].getboolean('random_gradient', fallback=False))
        self.chk_rand_frame.SetValue(self.cfg['Background'].getboolean('random_frame', fallback=False))
        self.spn_frame_thick.SetValue(int(self.cfg['Background'].get('frame_thickness', str(RenderSettings.frame_thickness))))
        
        # Store colors in temp vars for retrieval, widgets don't show color directly except via dialog
        self.current_font_color = self.cfg['Font'].get('color', '#ffffff')
        self.bg_solid = self.cfg['Background'].get('solid_color', '#000000')
        self.bg_start = self.cfg['Background'].get('grad_start', '#0a0a0a')
        self.bg_end = self.cfg['Background'].get('grad_end', '#404040')
        self.bg_frame = self.cfg['Background'].get('frame_color', '#ffffff')
        cfg_font = self.cfg['Font'].get('path', '').strip()
        
        if cfg_font:
            self.current_font_path = cfg_font
        
        self.current_bg_image = self.cfg['Background'].get('image', '')
    
    def _gather_render_settings(self) -> RenderSettings:
        rs = RenderSettings
        
        size = self.ch_size.GetStringSelection()
        rs.page_w, rs.page_w = map(int, size.split('x'))
        
        doc_type = self.doc_type.GetSelection()
        doc_size = self.doc_sizes[doc_type][-1]
        rs.max_w, rs.max_h = map(int, doc_size.split('x'))
        
        rs.panel_w, rs.panel_h = self.preview_panel.GetClientSize()
        
        rs.word_wrap = self.chk_wrap.GetValue()
        
        rs.font_size = self.spn_font_size.GetValue()
        rs.font_color = hex_to_rgb(self.current_font_color)
        rs.font_path = self.current_font_path if self.current_font_path else None
        
        rs.background_mode = self.ch_bg_mode.GetStringSelection()
        rs.invert = self.chk_invert.GetValue()
        rs.random_style_gradient = self.chk_rand_grad.GetValue()
        rs.random_style_frame = self.chk_rand_frame.GetValue()
        rs.frame_thickness = self.spn_frame_thick.GetValue()
        
        rs.bg_color = hex_to_rgb(self.bg_solid)
        rs.grad_start = hex_to_rgb(self.bg_start)
        rs.grad_end = hex_to_rgb(self.bg_end)
        rs.frame_color = hex_to_rgb(self.bg_frame)
        rs.background_image = self.current_bg_image if Path(self.current_bg_image).exists() else None
        
        return rs
    
    def on_save_settings(self, event):
        self.cfg['General']['merge_files'] = '1' if self.chk_merge.GetValue() else '0'
        self.cfg['General']['keep_temp'] = '1' if self.chk_keep.GetValue() else '0'
        
        self.cfg['Font']['size'] = str(self.spn_font_size.GetValue())
        self.cfg['Font']['color'] = self.current_font_color
        self.cfg['Font']['path'] = self.current_font_path
        
        self.cfg['Layout']['word_wrap'] = '1' if self.chk_wrap.GetValue() else '0'
        
        rs = RenderSettings
        self.cfg['Layout']['margin_top']    = str(rs.margin_top)
        self.cfg['Layout']['margin_left']   = str(rs.margin_left)
        self.cfg['Layout']['margin_right']  = str(rs.margin_right)
        self.cfg['Layout']['margin_bottom'] = str(rs.margin_bottom)
        self.cfg['Layout']['line_spacing']  = str(rs.line_spacing)
        self.cfg['Layout']['indent']        = str(rs.indent_first_line)
        
        self.cfg['Background']['mode'] = self.ch_bg_mode.GetStringSelection()
        self.cfg['Background']['invert'] = '1' if self.chk_invert.GetValue() else '0'
        self.cfg['Background']['random_gradient'] = '1' if self.chk_rand_grad.GetValue() else '0'
        self.cfg['Background']['random_frame'] = '1' if self.chk_rand_frame.GetValue() else '0'
        self.cfg['Background']['frame_thickness'] = str(self.spn_frame_thick.GetValue())
        
        self.cfg['Background']['solid_color'] = self.bg_solid
        self.cfg['Background']['grad_start'] = self.bg_start
        self.cfg['Background']['grad_end'] = self.bg_end
        self.cfg['Background']['frame_color'] = self.bg_frame
        self.cfg['Background']['image'] = self.current_bg_image
        
        self.cfg['Output']['type'] = str(self.doc_type.GetSelection())
        self.cfg['Output']['size'] = self.ch_size.GetStringSelection()
        
        self._save_config_file()
        wx.MessageBox('Settings saved successfully.', 'Info', wx.OK | wx.ICON_INFORMATION)
    
    def find_index(self, lst, value):
        try:
            return lst.index(value)
        except ValueError:
            return len(lst) - 1
    
    def update_doc_sizes_widget(self, doc_type, sel_size = ''):
        doc_sizes = self.doc_sizes[doc_type]
        
        size_idx = self.find_index(doc_sizes, sel_size) if sel_size != '' else self.ch_size.GetSelection()
        size_idx = size_idx if 0 <= size_idx < len(doc_sizes) else len(doc_sizes) - 1
        
        self.ch_size.Clear()
        self.ch_size.AppendItems(doc_sizes)
        self.ch_size.SetSelection(size_idx)
    
    def _apply_doc_type_ui(self, value: int):
        if value == 1:
            self.btn_keysbin.Hide()
            self.btn_keyreset.Hide()
            self.update_doc_sizes_widget(value)
        
        if value == 0:
            self.btn_keysbin.Show()
            self.btn_keyreset.Show()
            self.update_doc_sizes_widget(value)
    
    def _on_doc_type_change(self, event):
        value = event.GetSelection()
        self._apply_doc_type_ui(value)
    
    def _on_set_extra(self, event):
        dlg = ExtraRenderParamsDialog(self.panel)
        
        try:
            if dlg.ShowModal() == wx.ID_OK:
                dlg.set_extra_params()
        finally:
            dlg.Destroy()
    
    # ---------------------------
    # File Management
    # ---------------------------
    def _open_keysbin(self, e):
        with wx.FileDialog(
            self,
            message='Choose KEYS.BIN',
            wildcard='Binary key file|KEYS.BIN',
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            
            fpath = dlg.GetPath()
            
            try:
                with open(fpath, 'rb') as f:
                    data = f.read()
            except OSError as e:
                wx.MessageBox(f'Failed to open file:\n{e}', 'Error', wx.OK | wx.ICON_ERROR)
                return
            
            if len(data) != 16:
                wx.MessageBox(
                    f'Invalid KEYS.BIN size!\n'
                    f'Expected: 16 bytes\n'
                    f'Actual: {len(data)} bytes',
                    'Invalid Key File',
                    wx.OK | wx.ICON_ERROR
                )
                return
            
            self.key_bytes = data
            
            tt = self.btn_keysbin.GetToolTipText().splitlines()
            tt[-1] = data.hex(' ').upper()
            self.btn_keysbin.SetToolTip('\n'.join(tt))
            
            wx.MessageBox(
                f'Key loaded successfully:\n{data.hex(' ').upper()}',
                'Key OK',
                wx.OK | wx.ICON_INFORMATION
            )
    
    def _reset_keysbin(self, e):
        self.key_bytes = POPS_VER_KEY
        
        tt = self.btn_keysbin.GetToolTipText().splitlines()
        tt[-1] = self.key_bytes.hex(' ').upper()
        self.btn_keysbin.SetToolTip('\n'.join(tt))
        
        wx.MessageBox(
            f'Key was reset to:\n{self.key_bytes.hex(' ').upper()}',
            'Key Reset OK',
            wx.OK | wx.ICON_INFORMATION
        )
    
    def _refresh_list(self):
        self.lst_files.Clear()
        for i, p in enumerate(self.inputs):
            self.lst_files.Append(f'{i+1:03d}: {p.name}')
    
    def on_add_files(self, event):
        with wx.FileDialog(self, 'Open files', wildcard='Supported files|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.txt;*.dat|All files|*.*',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as fd:
            if fd.ShowModal() == wx.ID_CANCEL:
                return
            paths = [Path(p) for p in fd.GetPaths()]
            self._process_added_paths(paths)
    
    def on_add_folder(self, event):
        with wx.DirDialog(self, 'Select folder', style=wx.DD_DEFAULT_STYLE) as dd:
            if dd.ShowModal() == wx.ID_CANCEL:
                return
            folder = Path(dd.GetPath())
            paths = list_image_files(folder) + list_text_files(folder) + list(folder.rglob('*.dat'))
            self._process_added_paths(paths)
    
    def _process_added_paths(self, paths: List[Path]):
        dats = [p for p in paths if is_dat_file(p)]
        if dats:
            dlg = wx.MessageDialog(self, 'DAT file(s) detected. Extract PNGs?', 'DAT Detected', wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self._set_ui_busy(True)
                self._update_status('Extracting...')
                no_png_dats = []
                for di in range(len(dats)):
                    out_dir = dats[di].with_suffix('')
                    extracted = extract_pngs_from_dat(dats[di], out_dir)
                    if extracted:
                        self.inputs.extend(extracted)
                    else:
                        no_png_dats.append(dats[di].name)
                self._set_ui_busy(False)
                if no_png_dats:
                    wx.MessageBox('No PNGs found in:\n\n' + '\n'.join(no_png_dats), 'Warning', wx.ICON_WARNING)
                self._update_status('Ready')
            paths = [p for p in paths if not is_dat_file(p)]
        
        for p in paths:
            if p.exists():
                self.inputs.append(p)
        
        self._refresh_list()
    
    def on_remove(self, event):
        selections = self.lst_files.GetSelections()
        if not selections: return
        # Remove in reverse order
        for idx in sorted(selections, reverse=True):
            if 0 <= idx < len(self.inputs):
                self.inputs.pop(idx)
        self._refresh_list()
    
    def on_clear(self, event):
        self.inputs.clear()
        self._refresh_list()
    
    def on_move(self, delta):
        selections = self.lst_files.GetSelections()
        if len(selections) != 1: return
        i = selections[0]
        j = i + delta
        if 0 <= j < len(self.inputs):
            self.inputs[i], self.inputs[j] = self.inputs[j], self.inputs[i]
            self._refresh_list()
            self.lst_files.SetSelection(j)
    
    def reset_temp_dir(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        ensure_dir(self.temp_dir)
    
    # ---------------------------
    # Color & Font Pickers
    # ---------------------------
    def _pick_color(self, title, current_hex):
        data = wx.ColourData()
        try:
            rgb = hex_to_rgb(current_hex)
            data.SetColour(wx.Colour(*rgb))
        except: pass
        
        with wx.ColourDialog(self, data) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                return wx_col_to_hex(dlg.GetColourData().GetColour())
        return None
    
    def on_pick_font_color(self, e):
        c = self._pick_color('Font Color', self.current_font_color)
        if c: self.current_font_color = c
    
    def on_pick_bg_color(self, e):
        c = self._pick_color('Background Color', self.bg_solid)
        if c: self.bg_solid = c
    
    def on_pick_grad(self, which):
        curr = self.bg_start if which == 'start' else self.bg_end
        c = self._pick_color(f'Gradient {which}', curr)
        if c:
            if which == 'start': self.bg_start = c
            else: self.bg_end = c
    
    def on_pick_frame_color(self, e):
        c = self._pick_color('Frame Color', self.bg_frame)
        if c: self.bg_frame = c
    
    def _ensure_default_font(self):
        # Ensure a valid default font is selected using FontResolver.
        
        cfg_path = self.cfg['Font'].get('path', '').strip()
        if cfg_path:
            try:
                ImageFont.truetype(cfg_path, self.spn_font_size.GetValue())
                self.current_font_path = cfg_path
                return
            except Exception:
                pass  # fallback below
        
        wx_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        
        font_path = self.font_resolver.resolve(wx_font)
        if font_path:
            self.current_font_path = font_path
            return
        
        if sys.platform.startswith('win'):
            fallback = Path(os.environ.get('WINDIR', 'C:\\Windows')) / 'Fonts' / 'arial.ttf'
        else:
            fallback = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        
        if fallback.exists():
            self.current_font_path = str(fallback)
            return
        
        wx.MessageBox(
            'No usable font could be found on this system.\n'
            'Please select a font manually.',
            'Font error',
            wx.OK | wx.ICON_ERROR,
            parent=self,
        )
    
    def on_pick_font(self, e):
        data = wx.FontData()
        data.EnableEffects(False)
        
        init_font_size = int(self.spn_font_size.GetValue() or RenderSettings.font_size)
        
        try:
            ft = ImageFont.truetype(self.current_font_path, size=max(1, init_font_size))
            faceName, _ = ft.getname()
        except Exception:
            faceName = ''
        
        init_font = wx.Font(
            pointSize = init_font_size,
            family = wx.FONTFAMILY_DEFAULT,
            style = wx.FONTSTYLE_NORMAL,
            weight = wx.FONTWEIGHT_NORMAL,
            faceName = faceName,
        )
        
        data.SetInitialFont(init_font)
        data.SetRange(8, 72)
        
        with wx.FontDialog(self, data) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            
            wx_font = dlg.GetFontData().GetChosenFont()
            
            font_path = self.font_resolver.resolve(wx_font)
            if not font_path:
                wx.MessageBox(
                    'Cannot locate font file for selected font.\n'
                    'Please choose another font.',
                    'Font error',
                    wx.OK | wx.ICON_WARNING,
                    parent=self,
                )
                return
            
            self.spn_font_size.SetValue(wx_font.GetPointSize())
            self.current_font_path = font_path
    
    def on_pick_bg_image(self, e):
        with wx.FileDialog(self, 'Select BG Image', wildcard='Images|*.png;*.jpg;*.jpeg;*.bmp', style=wx.FD_OPEN) as fd:
            if fd.ShowModal() == wx.ID_OK:
                self.current_bg_image = fd.GetPath()
    
    def on_clear_bg_image(self, e):
        self.current_bg_image = ''
    
    # ---------------------------
    # Preview
    # ---------------------------
    def _show_preview_page(self):
        if not self.preview_pages:
            self.preview_canvas.SetBitmap(wx.NullBitmap)
            self.st_page.SetLabel('NO PREVIEW')
            return
        
        p = self.preview_pages[self.preview_index]
        
        img = wx.Image(str(p), wx.BITMAP_TYPE_ANY)
        
        w, h = self.preview_panel.GetClientSize()
        if w < 10 or h < 10:
            return
        
        iw, ih = img.GetWidth(), img.GetHeight()
        ratio = min(w / iw, h / ih)
        nw, nh = max(1, int(iw * ratio)), max(1, int(ih * ratio))
        
        img = img.Scale(nw, nh, wx.IMAGE_QUALITY_HIGH)
        bmp = wx.Bitmap(img)
        
        self.preview_canvas.SetBitmap(bmp)
        self.preview_bitmap = bmp
        
        self.st_page.SetLabel(
            f'PREVIEW PAGE: {self.preview_index + 1:04d} / {len(self.preview_pages):04d}'
        )
        
        self.preview_panel.Layout()
    
    def _preview_step(self, delta):
        if not self.preview_pages:
            return
        self.preview_index = (self.preview_index + delta) % len(self.preview_pages)
        self._show_preview_page()
    
    def _on_preview_resize(self, event):
        if self.preview_bitmap:
            self._show_preview_page()
        event.Skip()
    
    # ---------------------------
    # Rendering & Actions
    # ---------------------------
    def _update_status(self, msg):
        self.st_status.SetLabel(msg)
        # wx.GetApp().Yield()
        wx.YieldIfNeeded()
    
    def _render_all_logic(self, rs: RenderSettings, files: list[Path], for_file: bool, progress_cb):
        width_cache.clear()
        self.reset_temp_dir()
        
        pages: List[Image.Image] = []
        page_index = 0
        
        def add_pages(new_pages):
            nonlocal page_index
            for im in new_pages:
                pages.append(im)
                page_index += 1
        
        for p in files:
            progress_cb(f'Rendering {p.name}')
            if p.suffix.lower() == '.txt':
                enc = detect_text_encoding(p)
                text = p.read_text(encoding=enc, errors='replace')
                add_pages(render_text_to_pages(text, rs, page_index))
            else:
                add_pages([render_image_to_page(p, rs, for_file, page_index)])
        
        return pages
    
    def _start_render_thread(self, for_file: bool = False):
        merge = self.chk_merge.GetValue()
        
        def progress_cb(msg):
            wx.CallAfter(self._update_progress, msg)
        
        if not merge:
            sel = self.lst_files.GetSelections()
            if not sel:
                wx.MessageBox(
                    'Please select a files to render\nor enable "Merge all to one".',
                    'No file selected',
                    wx.OK | wx.ICON_WARNING,
                )
                return
            files = list()
            for i in range(len(sel)):
                files.append(self.inputs[sel[i]])
        else:
            files = list(self.inputs)
        
        self._set_ui_busy(True)
        self.gauge.SetRange(100)
        self.gauge.Pulse()
        self.st_status.SetLabel('Rendering pages…')
        
        rs = self._gather_render_settings()
        
        def worker():
            try:
                pages = self._render_all_logic(rs, files, for_file, progress_cb)
                wx.CallAfter(self._on_render_done, pages, for_file)
            except Exception as e:
                wx.CallAfter(wx.MessageBox, str(e), 'Render error', wx.ICON_ERROR)
            finally:
                wx.CallAfter(self._set_ui_busy, False)
        
        threading.Thread(target=worker, daemon=True).start()
    
    def _update_progress(self, msg):
        self.st_status.SetLabel(msg)
    
    def _on_render_done(self, pages, for_file):
        self.preview_pages.clear()
        self.gauge.SetRange(len(pages))
        self.gauge.SetValue(0)
        self.st_status.SetLabel('Saving pages…')
        
        for i, im in enumerate(pages):
            out = self.temp_dir / f'{i+1:04d}.png'
            im.save(out, 'PNG', optimize=True)
            self.preview_pages.append(out)
            self.st_status.SetLabel(f'Saving pages {i+1}/{len(pages)}...')
            self.gauge.SetValue(i+1)
        
        self.preview_index = 0
        self._show_preview_page()
        self.st_status.SetLabel(f'Rendered {len(pages)} pages.')
        self.gauge.SetValue(self.gauge.GetRange())
        
        if for_file:
            try:
                self._update_status('Packing DAT...')
                pack_pngs_to_dat(self.doc_game_id, self.doc_type.GetSelection(), self.key_bytes, self.preview_pages, self.dest_dir)
                self._update_status('Done.')
            except Exception as e:
                wx.MessageBox(str(e), 'Error', wx.ICON_ERROR)
           
        if for_file and not self.chk_keep.GetValue():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            
            self.preview_pages.clear()
            self.preview_canvas.SetBitmap(wx.NullBitmap)
            self.st_page.SetLabel('EMPTY')
            self.preview_index = 0
    
    def _set_ui_busy(self, busy: bool):
        for btn in (
            # files / folders
            self.lst_files,
            self.btn_add_files,
            self.btn_add_folder,
            self.btn_remove,
            self.btn_up,
            self.btn_down,
            self.btn_clear,
            self.btn_setgameid,
            # preview
            self.btn_prev,
            self.btn_next,
            # doc specific
            self.doc_type,
            self.btn_keysbin,
            self.btn_keyreset,
            # set text
            self.ch_size,
            self.chk_wrap,
            self.chk_merge,
            self.chk_keep,
            self.spn_font_size,
            self.btn_font_path,
            self.btn_font_color,
            self.btn_set_extra,
            # set background
            self.ch_bg_mode,
            self.chk_invert,
            self.chk_rand_grad,
            self.chk_rand_frame,
            self.btn_bg_solid,
            self.btn_bg_start,
            self.btn_bg_end,
            self.btn_bg_frame,
            self.spn_frame_thick,
            self.btn_bg_img,
            self.btn_clr_bg_img,
            # buttons
            self.btn_preview,
            self.btn_create,
            self.btn_extract,
            self.btn_save_cfg,
        ):
            btn.Enable(not busy)
    
    def on_setgameid(self, event):
        dlg = GameIdDialog(self.panel, self.doc_game_id)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                game_id = dlg.GetValue()
                self.doc_game_id = game_id
                self.btn_setgameid.SetLabel(game_id)
        finally:
            dlg.Destroy()
    
    def on_preview_all(self, event):
        if not self.inputs:
            wx.MessageBox('Add images or text files first.', 'Info')
            return
        
        self._start_render_thread()
    
    def on_preview_selected(self):
        sel = self.lst_files.GetSelections()
        if not sel:
            self.on_preview_all(None)
            return
        
        idx = sel[0]
        p = self.inputs[idx]
        rs = self._gather_render_settings()
        
        self.reset_temp_dir()
        
        try:
            if p.suffix.lower() == '.txt':
                enc = detect_text_encoding(p)
                text = p.read_text(encoding=enc, errors='replace')
                pages = render_text_to_pages(text, rs)
            else:
                pages = [render_image_to_page(p, rs)]
            
            self.preview_pages = []
            for i, im in enumerate(pages):
                out = self.temp_dir / f'{i + 1:04d}.png'
                im.save(out, format='PNG')
                self.preview_pages.append(out)
            
            self.preview_index = 0
            self._show_preview_page()
        
        except Exception as e:
            wx.MessageBox(str(e), 'Error', wx.ICON_ERROR)
    
    def on_create_dat(self, event):
        if not self.inputs:
            wx.MessageBox('Add images or text files first.', 'Info')
            return
        
        with wx.DirDialog(self, 'Select output folder', style=wx.DD_DEFAULT_STYLE) as dd:
            if dd.ShowModal() == wx.ID_CANCEL: return
            self.dest_dir = Path(dd.GetPath())
            self._start_render_thread(for_file = True)
    
    def on_extract_dat(self, event):
        with wx.FileDialog(self, 'Select DOCUMENT.DAT', wildcard='DAT files (*.dat)|*.dat', style=wx.FD_OPEN) as fd:
            if fd.ShowModal() == wx.ID_CANCEL: return
            dat_path = Path(fd.GetPath())
        
        with wx.DirDialog(self, 'Select output folder', style=wx.DD_DEFAULT_STYLE) as dd:
            if dd.ShowModal() == wx.ID_CANCEL: return
            out_dir = Path(dd.GetPath())
        
        try:
            self._update_status('Extracting...')
            files = extract_pngs_from_dat(dat_path, out_dir)
            if len(files) > 0:
                wx.MessageBox(f'Extracted {len(files)} images.', 'Success')
            else:
                wx.MessageBox(f'No PNGs found in:\n\n{dat_path}', 'Warning', wx.ICON_WARNING)
            self._update_status('Ready')
        except Exception as e:
            wx.MessageBox(str(e), 'Error')

class GameIdDialog(wx.Dialog):
    def __init__(self, parent, GameId):
        super().__init__(parent, title="Enter Game ID")
        
        self.txt = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.txt.SetMaxLength(9)
        
        if GameId:
            self.txt.SetValue(str(GameId).strip().upper())
            self.txt.SetSelection(-1, -1)
        
        ok = wx.Button(self, wx.ID_OK, "OK")
        cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        ok.SetDefault()
        
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(wx.StaticText(self, label="Format: XXXXYYYYY (X=letter, Y=number)"), 0, wx.ALL, 8)
        s.Add(self.txt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        
        btns = wx.BoxSizer(wx.HORIZONTAL)
        btns.AddStretchSpacer(1)
        btns.Add(cancel, 0, wx.ALL, 8)
        btns.Add(ok, 0, wx.ALL, 8)
        
        s.Add(btns, 0, wx.EXPAND)
        self.SetSizerAndFit(s)
        self.CentreOnParent()
        
        self.Bind(wx.EVT_TEXT, self.on_text, self.txt)
        self.Bind(wx.EVT_TEXT_ENTER, lambda e: self.EndModal(wx.ID_OK), self.txt)
        self.Bind(wx.EVT_BUTTON, self.on_ok, ok)
    
    def on_text(self, event):
        val = self.txt.GetValue()
        
        filtered = "".join(ch for ch in val if ch.isalnum()).upper()[:9]
        
        # Enforce per-position constraints
        out = []
        for i, ch in enumerate(filtered):
            if i < 4:
                if ch.isalpha():
                    out.append(ch)
            else:
                if ch.isdigit():
                    out.append(ch)
        
        new_val = "".join(out)
        
        if new_val != val:
            pos = self.txt.GetInsertionPoint()
            self.txt.ChangeValue(new_val)
            self.txt.SetInsertionPoint(min(pos, len(new_val)))
        
        event.Skip()
    
    def on_ok(self, event):
        value = self.txt.GetValue().strip().upper()
        if not GAMEID_PATTERN.match(value):
            wx.MessageBox(
                "Invalid format.\n\nUse: XXXXYYYYY\n(4 letters + 5 digits)",
                "Error",
                wx.ICON_ERROR | wx.OK,
                parent=self
            )
            return
        self.EndModal(wx.ID_OK)
    
    def GetValue(self):
        return self.txt.GetValue().strip().upper()

if __name__ == '__main__':
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
