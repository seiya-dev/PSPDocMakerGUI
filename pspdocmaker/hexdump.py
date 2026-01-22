# coding: utf-8

def hexdump(data: bytes, start_offset: int = 0) -> str:
    if start_offset < 0:
        raise ValueError('start_offset must be >= 0')
    
    fmt = '{:08x}  {:23}  {:23}  |{:16}|'
    base, pad, i, out = start_offset & ~0xF, start_offset & 0xF, 0, []
    
    hx = lambda bs: ' '.join(('  ' if b is None else f'{b:02x}') for b in bs).ljust(23)
    asc = lambda bs: ''.join('.' if b is None else (chr(b) if 32 <= b <= 126 else '.') for b in bs)
    
    while i < len(data):
        take = min(16 - pad, len(data) - i)
        cells = [None] * pad + list(data[i:i + take]) + [None] * (16 - pad - take)
        out.append(fmt.format(base, hx(cells[:8]), hx(cells[8:]), asc(cells)))
        i, base, pad = i + take, base + 16, 0
    
    out.append(f'{start_offset + len(data):08x}')
    return '\n'.join(out)
