from typing import List, Tuple, Optional, Iterable
from pathlib import Path
import hashlib
import struct
import hmac
import os

import wx
from .hexdump import hexdump
from .utils import ensure_dir
from .bboxmin import boxbb_mac_gen_enc

try:
    from Crypto.Cipher import DES
except ImportError as e:
    raise SystemExit('This app requires Crypto. Install with: pip install pycryptodome') from e

PS1_DES_KEY = bytes([0x39, 0xF7, 0xEF, 0xA1, 0x6C, 0xCE, 0x5F, 0x4C])
PS1_DES_IV  = bytes([0xA8, 0x19, 0xC4, 0xF5, 0xE1, 0x54, 0xE3, 0x0B])

PSP_DES_KEY = bytes([0xDA, 0x39, 0x23, 0xEF, 0x9C, 0x61, 0xB9, 0x30])
PSP_DES_IV  = bytes([0x2D, 0xEE, 0x89, 0x50, 0x96, 0x91, 0x12, 0xD9])

PSP_HMAC_KEY = bytes([0x4D, 0x1B, 0x6B, 0x12, 0x69, 0xDD, 0xD2, 0x2F, 0xAA, 0xE1, 0xF5, 0x42, 0x07, 0xE7, 0x98, 0xB5])
PS3_HMAC_KEY = bytes([0xEF, 0x69, 0x0E, 0xC0, 0xE0, 0xBF, 0xA4, 0x1F, 0x08, 0x45, 0x5B, 0xD0, 0x38, 0xEB, 0x87, 0x62])

def desEncrypt(doc_type: int, data: bytes) -> bytes:
    DES_KEY = PS1_DES_KEY if doc_type == 0 else PSP_DES_KEY
    DES_IV  = PS1_DES_IV  if doc_type == 0 else PSP_DES_IV
    
    cipher = DES.new(DES_KEY, DES.MODE_CBC, DES_IV)
    return cipher.encrypt(data)

def sha1hash(data: bytes) -> bytes:
    return hashlib.sha1(data).digest()[:0x10]

def sha1hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha1).digest()[:0x10]

def gen_pad(buf: bytes, block_size: int = 16) -> bytes:
    return buf + b'\x00' * (-len(buf) % block_size)

def create_header(gameid, pages):
    buf = bytearray(0x60)
    struct.pack_into('<I', buf, 0x00, 0x20434F44)
    struct.pack_into('<I', buf, 0x04, 0x10000)
    struct.pack_into('<I', buf, 0x08, 0x10000)
    buf[0x0C:0x1C] = gameid.encode('ascii')[:0x0F].ljust(0x10, b'\x00')
    struct.pack_into('<I', buf, 0x1C, 0 if len(pages) < 100 else 1)
    return buf

def pack_pngs_to_dat(doc_type: int, ins_id: bytes, png_paths: List[Path], out_dir: Path) -> None:
    out_dat = out_dir / 'DOCUMENT.DAT'
    out_key = out_dir / 'KEYS.BIN'
    ensure_dir(out_dir)
    
    if os.path.exists(out_dat):
        ow_dlg = wx.MessageDialog(
            wx.GetApp().GetTopWindow(),
            f"The file:\n\n{out_dat}\n\nalready exists.\nDo you want to overwrite it?",
            "Confirm Overwrite",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )
        ow_ans = ow_dlg.ShowModal()
        ow_dlg.Destroy()
        
        if ow_ans != wx.ID_YES:
            return
    
    if len(png_paths) > 999:
        wx.MessageBox('Maximum 999 pages allowed, pages starting from 1000 will not be written!', 'Warning', wx.ICON_WARNING)
        del png_paths[999:]
    
    if doc_type not in (0, 1):
        wx.MessageBox(f'Bad DOC parameters', 'Error', wx.ICON_ERROR)
        return
    
    pgd_buf = b'\0PGD\1\0\0\0\1\0\0\0\0\0\0\0'
    doc_hdr = desEncrypt(doc_type, create_header('DOCMAKERNX', png_paths))
    
    if doc_type == 0:
        pgd_buf += doc_hdr + boxbb_mac_gen_enc(doc_hdr, ins_id) + sha1hash(doc_hdr)
    if doc_type == 1:
        pgd_buf += doc_hdr + bytes(0x10) + sha1hmac(PSP_HMAC_KEY, doc_hdr) + sha1hmac(PS3_HMAC_KEY, doc_hdr)
    
    pages = []
    for p in png_paths:
        pages.append(gen_pad(p.read_bytes()))
    
    page_count = len(pages)
    
    info_block_size = 0x31e8 if page_count < 100 else 0x1f3e8
    info_buffer = bytearray(info_block_size)
    
    ps3_page_count_offset = 0x3188 if page_count < 100 else 0x1f388
    
    hash_block_size = 0x20 if doc_type == 0 else 0x30
    page_offset = len(pgd_buf) + info_block_size + hash_block_size + 0x08
    
    struct.pack_into('<I', info_buffer, 0x00, 0xffffffff)
    struct.pack_into('<I', info_buffer, 0x04, page_count)
    struct.pack_into('<I', info_buffer, ps3_page_count_offset, page_count)
    
    for i, p in enumerate(pages):
        page_len = 0x20 + len(p) + hash_block_size
        struct.pack_into('<I', info_buffer, 0x08 + i * 0x80 + 0x00, page_offset)
        struct.pack_into('<I', info_buffer, 0x08 + i * 0x80 + 0x0c, page_len)
        struct.pack_into('<I', info_buffer, 0x08 + i * 0x80 + 0x10, page_offset)
        struct.pack_into('<I', info_buffer, 0x08 + i * 0x80 + 0x1c, page_len)
        page_offset += page_len
    
    info_buffer = desEncrypt(doc_type, info_buffer)
    
    if doc_type == 0:
        pgd_buf += info_buffer + boxbb_mac_gen_enc(info_buffer, ins_id) + sha1hash(info_buffer)
    if doc_type == 1:
        pgd_buf += info_buffer + bytes(0x10) + sha1hmac(PSP_HMAC_KEY, info_buffer) + sha1hmac(PS3_HMAC_KEY, info_buffer)
    
    pgd_buf += bytes(0x08)
    
    for i, p in enumerate(pages):
        page_len = 0x20 + len(p) + hash_block_size
        page_info_head = bytearray(0x20)
        struct.pack_into('<I', page_info_head, 0, page_len)
        
        p = desEncrypt(doc_type, page_info_head) + p
        
        if doc_type == 0:
            pgd_buf += p + boxbb_mac_gen_enc(p, ins_id) + sha1hash(p)
        if doc_type == 1:
            pgd_buf += p + bytes(0x10) + sha1hmac(PSP_HMAC_KEY, p) + sha1hmac(PS3_HMAC_KEY, p)
    
    with out_dat.open('wb') as f:
        f.write(pgd_buf)
    
    if doc_type == 0:
        write_key = True
        
        if os.path.exists(out_key):
            with open(out_key, "r", encoding="utf-8") as f:
                e_key = f.read()
            
            if e_key != ins_id and len(e_key) == 0x10:
                owk_dlg = wx.MessageDialog(
                    wx.GetApp().GetTopWindow(),
                    f"The file:\n\n{out_key}\n\nalready exists.\nDo you want to overwrite it?",
                    "Confirm Overwrite",
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
                )
            
                owk_ans = owk_dlg.ShowModal()
                owk_dlg.Destroy()
            
                if owk_ans != wx.ID_YES:
                    write_key = False
        
        if write_key:
            with out_key.open('wb') as f:
                f.write(ins_id)
            out_dat = str(out_dat) +  '\n' + str(out_key)
    
    wx.MessageBox(f'Created:\n{out_dat}', 'Success', wx.OK | wx.ICON_INFORMATION)

def extract_pngs_from_dat(dat_path: Path, out_dir: Path) -> List[Path]:
    data = dat_path.read_bytes()
    ensure_dir(out_dir)
    out_files = []
    idx = 0
    for blob in iter_png_blobs_from_dat(data):
        out = out_dir / f'DOC_{idx + 1:04d}.png'
        out.write_bytes(blob)
        out_files.append(out)
        idx += 1
    return out_files

def iter_png_blobs_from_dat(data: bytes) -> Iterable[bytes]:
    PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
    
    i = 0
    n = len(data)
    
    while True:
        s = data.find(PNG_SIGNATURE, i)
        if s < 0:
            return
        p = s + len(PNG_SIGNATURE)
        try:
            while p + 8 <= n:
                length = int.from_bytes(data[p:p+4], 'big', signed=False)
                ctype = data[p+4:p+8]
                p += 8
                if p + length + 4 > n:
                    raise ValueError('Truncated chunk')
                p += length  # chunk data
                p += 4       # crc
                if ctype == b'IEND':
                    blob = data[s:p]
                    yield blob
                    i = p
                    break
            else:
                i = s + 1
        except Exception:
            i = s + 1
