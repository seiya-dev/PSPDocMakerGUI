# coding: utf-8
# BBOX minimal implementation for encrypted PS1 DOCUMENT.DAT

from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from Crypto.Cipher import AES

class BBoxException(Exception):
    def __init__(self, code: int, message: str = ''):
        super().__init__(message or f'BBox Error')

def _raise(code: int, msg: str) -> None:
    raise BBoxException(msg)

KEY_VAULT = {
    0x03: bytes([0xE3, 0x50, 0xED, 0x1D, 0x91, 0x0A, 0x1F, 0xD0, 0x29, 0xBB, 0x1C, 0x3E, 0xF3, 0x40, 0x77, 0xFB]),
    0x38: bytes([0x12, 0x46, 0x8D, 0x7E, 0x1C, 0x42, 0x20, 0x9B, 0xBA, 0x54, 0x26, 0x83, 0x5E, 0xB0, 0x33, 0x03]),
    0x63: bytes([0x9C, 0x9B, 0x13, 0x72, 0xF8, 0xC6, 0x40, 0xCF, 0x1C, 0x62, 0xF5, 0xD5, 0x92, 0xDD, 0xB5, 0x82]),
}

def _encrypt_iv0(data: bytes, keyseed: int) -> bytes:
    return AES.new(KEY_VAULT[keyseed], AES.MODE_CBC, b'\x00' * 16).encrypt(data)

def _decrypt_iv0(data: bytes, keyseed: int) -> bytes:
    return AES.new(KEY_VAULT[keyseed], AES.MODE_CBC, b'\x00' * 16).decrypt(data)

@dataclass
class MACKey:
    key: bytearray
    pad: bytearray
    pad_size: int

def BBMacInit(mkey: MACKey) -> int:
    mkey.pad_size = 0
    mkey.key[:] = b'\x00' * 0x10
    mkey.pad[:] = b'\x00' * 0x10

def _sub_158_encrypt_block(block: bytes, key: bytearray, key_type: int) -> Tuple[bytes, bytes]:
    if len(block) % 0x10 != 0:
        _raise('Encrypt block size must be multiple of 16')
    
    b = bytearray(block)
    for i in range(0x10):
        b[i] ^= key[i]
    
    ct = _encrypt_iv0(bytes(b), key_type)
    
    key_next = ct[-0x10:] if len(ct) >= 0x10 else (b'\x00' * 0x10)
    return ct, key_next

def BBMacUpdate(mkey: MACKey, buf: bytes):
    if mkey.pad_size > 16:
        _raise('MAC Key padding size must be do not exceed 16 bytes')
    
    size = len(buf)
    data = memoryview(buf)
    
    if mkey.pad_size + size <= 16:
        mkey.pad[mkey.pad_size:mkey.pad_size + size] = data.tobytes()
        mkey.pad_size += size
        return
    
    stream = bytes(mkey.pad[:mkey.pad_size]) + data.tobytes()
    
    rem = (mkey.pad_size + size) & 0x0F
    if rem == 0:
        rem = 16
    
    full_len = len(stream) - rem
    tail = stream[full_len:]
    mkey.pad[:rem] = tail
    mkey.pad_size = rem
    
    p = 0
    while p < full_len:
        chunk = stream[p:p + min(0x0800, full_len - p)]
        ct, key_next = _sub_158_encrypt_block(chunk, mkey.key, 0x38)
        mkey.key[:] = key_next
        p += len(chunk)

def left_shift_1(block16: bytes) -> bytes:
    b = bytearray(16)
    carry = 0
    for i in reversed(range(16)):
        v = block16[i]
        b[i] = ((v << 1) & 0xFF) | carry
        carry = 1 if (v & 0x80) else 0
    if carry:
        b[15] ^= 0x87
    return bytes(b)

def BBMacFinal(mkey: MACKey, out16: bytearray, vkey: Optional[bytes]) -> int:
    if mkey.pad_size > 16:
        _raise('MAC Key padding size must be do not exceed 16 bytes')
    
    L = _encrypt_iv0(b'\x00' * 16, 0x38)
    
    K1 = left_shift_1(L)
    K2 = left_shift_1(K1)
    
    pad = bytearray(mkey.pad)
    if mkey.pad_size < 16:
        pad[mkey.pad_size] = 0x80
        for j in range(mkey.pad_size + 1, 16):
            pad[j] = 0x00
        subkey = K2
    else:
        subkey = K1
    
    for i in range(16):
        pad[i] ^= subkey[i]
    
    final_block = bytes(pad)
    ct, key_next = _sub_158_encrypt_block(final_block, mkey.key, 0x38)
    tmp1 = bytearray(ct[-16:])
    
    for i in range(16):
        tmp1[i] ^= KEY_VAULT[0x03][i]
    
    if vkey is not None:
        if len(vkey) != 16:
            _raise('Version Key must be 16 bytes')
        for i in range(16):
            tmp1[i] ^= vkey[i]
        tmp1 = bytearray(_encrypt_iv0(bytes(tmp1), 0x38))
    
    out16[:16] = tmp1[:16]
    
    mkey.key[:] = b'\x00' * 16
    mkey.pad[:] = b'\x00' * 16
    mkey.pad_size = 0

def bbmac_getkey(mkey: MACKey, bbmac: bytes) -> int:
    if len(bbmac) != 16:
        _raise('BB MAC must be exactly 16 bytes')
    
    tmp = bytearray(16)
    vkey_out = bytearray(16)
    BBMacFinal(mkey, tmp, None)
    
    mac_working = bytearray(bbmac)
    mac_working[:] = _decrypt_iv0(bytes(mac_working), 0x63)
    decrypted = _decrypt_iv0(bytes(mac_working), 0x38)
    
    for i in range(16):
        vkey_out[i] = tmp[i] ^ decrypted[i]
    
    return vkey_out

def pops_get_secure_install_id(buf: bytes) -> bytes:
    if len(buf) != 0x70:
        _raise('buf must be 0x70 bytes')
    
    mkey = MACKey(key=bytearray(16), pad=bytearray(16), pad_size=0)
    
    BBMacInit(mkey)
    BBMacUpdate(mkey, buf[:0x60])
    id_out = bbmac_getkey(mkey, buf[0x60:0x70])
    
    return id_out

def boxbb_mac_gen(buf: bytes, vkey: bytes) -> bytes:
    if len(vkey) != 16:
        _raise('version_key must be 16 bytes')
    
    buf = bytes(buf)
    tmp = bytearray(16)
    
    mkey = MACKey(key=bytearray(16), pad=bytearray(16), pad_size=0)
    
    BBMacInit(mkey)
    BBMacUpdate(mkey, buf)
    BBMacFinal(mkey, tmp, vkey)
    
    return bytes(tmp)

def boxbb_mac_gen_enc(buf: bytes, vkey: bytes) -> bytes:
    get_bb_mac =  boxbb_mac_gen(buf, vkey)
    return _encrypt_iv0(get_bb_mac, 0x63)
