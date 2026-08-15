from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else 'hangul_full16.h')
CANDIDATES = [
    '/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
]
font_path = next((p for p in CANDIDATES if Path(p).exists()), None)
if not font_path:
    raise SystemExit('Nanum Korean font not found')
font = ImageFont.truetype(font_path, 16)

def rows(ch):
    bbox = font.getbbox(ch)
    w, h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    im = Image.new('L', (16,16), 0)
    d = ImageDraw.Draw(im)
    x = (16-w)//2 - bbox[0]
    y = (16-h)//2 - bbox[1]
    d.text((x,y), ch, font=font, fill=255)
    out=[]
    for yy in range(16):
        bits=0
        for xx in range(16):
            if im.getpixel((xx,yy)) >= 96:
                bits |= 1 << (15-xx)
        out.append(bits)
    return out

extras = [
  0x3131,0x3132,0x3134,0x3137,0x3138,0x3139,0x3141,0x3142,0x3143,
  0x3145,0x3146,0x3147,0x3148,0x3149,0x314A,0x314B,0x314C,0x314D,0x314E,
  *range(0x314F,0x3164), 0x318D
]

with OUT.open('w', encoding='utf-8') as f:
    f.write('#pragma once\n#include <Arduino.h>\n\n')
    f.write('// Modern Hangul 16x16 fallback raster. Generated at CI build time.\n')
    f.write('// Source font: Nanum Korean font family (see THIRD_PARTY_NOTICES.md).\n')
    f.write('#define HANGUL16_FIRST 0xAC00u\n#define HANGUL16_COUNT 11172u\n')
    f.write('static const uint16_t HANGUL16_SYLLABLES[HANGUL16_COUNT * 16u] PROGMEM = {\n')
    vals=[]
    for cp in range(0xAC00,0xD7A4): vals.extend(rows(chr(cp)))
    for i in range(0,len(vals),12):
        f.write('  '+', '.join(f'0x{x:04X}u' for x in vals[i:i+12])+',\n')
    f.write('};\n\n')
    f.write('struct Hangul16ExtraGlyph { uint16_t cp; uint16_t row[16]; };\n')
    f.write(f'static const uint16_t HANGUL16_EXTRA_COUNT = {len(extras)}u;\n')
    f.write('static const Hangul16ExtraGlyph HANGUL16_EXTRA[] PROGMEM = {\n')
    for cp in extras:
        r=rows(chr(cp))
        f.write('  {0x%04Xu, {'%cp + ', '.join(f'0x{x:04X}u' for x in r) + '}},\n')
    f.write('};\n')

print(f'generated {OUT} using {font_path}, size={OUT.stat().st_size}')
