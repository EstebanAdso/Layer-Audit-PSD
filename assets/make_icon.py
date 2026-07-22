"""
make_icon.py
============
Genera el icono de la app "Layer Audit PSD".

Concepto: tres capas (rombos isometricos apilados) en degradado violeta
sobre un fondo morado-casi-negro con esquinas redondeadas. Comunica
"capas" (layers PSD) y encaja con el tema oscuro morado de la GUI.

Salida (junto a este script, en assets/):
    icon.png          1024x1024 master
    icon.ico          multi-size (16/32/48/64/128/256) para Windows + exe
    logo_header.png   64x64 para el header de la GUI

Uso:
    python assets/make_icon.py
"""

import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

# --- Paleta (alineada con el tema oscuro morado de gui.py) ---------------
BG_TOP    = (38, 22, 66)     # #261642  morado elevado (arriba)
BG_BOT    = (18, 11, 30)     # #120b1e  morado casi negro (abajo)
LAYER_HI  = (167, 139, 250)  # #a78bfa  violeta claro  (capa superior)
LAYER_MID = (139, 92, 246)   # #8b5cf6  violeta        (capa media)
LAYER_LO  = (109, 40, 217)   # #6d28d9  violeta profundo (capa inferior)
OUTLINE   = (14, 8, 24)      # separacion entre capas
GLOW      = (167, 139, 250)  # halo sutil bajo las capas

S = 1024  # lienzo master


def rounded_mask(size, radius):
    m = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def vertical_gradient(size, top, bottom):
    grad = Image.new('RGB', (size, size), top)
    d = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        d.line([(0, y), (size, y)], fill=(r, g, b))
    return grad


def rhombus(cx, cy, half_w, half_h):
    return [
        (cx, cy - half_h),
        (cx + half_w, cy),
        (cx, cy + half_h),
        (cx - half_w, cy),
    ]


def build_master():
    # Fondo con degradado y esquinas redondeadas.
    base = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    grad = vertical_gradient(S, BG_TOP, BG_BOT).convert('RGBA')
    base.paste(grad, (0, 0), rounded_mask(S, int(S * 0.235)))

    draw = ImageDraw.Draw(base)

    cx = S // 2
    half_w = int(S * 0.30)   # ancho del rombo
    half_h = int(S * 0.165)  # alto del rombo (isometrico ~2:1)
    gap = int(S * 0.135)     # separacion vertical entre capas
    ow = int(S * 0.012)      # grosor de la linea de separacion

    # Halo sutil detras de la capa inferior para dar profundidad.
    from PIL import ImageFilter
    glow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - half_w - 40, S // 2 + gap - 60,
                cx + half_w + 40, S // 2 + gap + 120],
               fill=GLOW + (60,))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base)

    # Tres capas de abajo hacia arriba.
    layers = [
        (S // 2 + gap, LAYER_LO),
        (S // 2,       LAYER_MID),
        (S // 2 - gap, LAYER_HI),
    ]
    for cy, color in layers:
        pts = rhombus(cx, cy, half_w, half_h)
        draw.polygon(pts, fill=color, outline=OUTLINE, width=ow)

    return base


def build_hero():
    """Ilustración para los estados vacíos: capas violeta flotando sobre un
    glow radial, fondo transparente (se compone sobre el panel de la GUI)."""
    from PIL import ImageFilter
    H = 640
    img = Image.new('RGBA', (H, H), (0, 0, 0, 0))

    # Glow radial violeta (circulo relleno + blur fuerte).
    glow = Image.new('RGBA', (H, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([H * 0.16, H * 0.20, H * 0.84, H * 0.88],
               fill=LAYER_MID + (120,))
    glow = glow.filter(ImageFilter.GaussianBlur(H * 0.10))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)
    cx = H // 2
    half_w = int(H * 0.28)
    half_h = int(H * 0.155)
    gap = int(H * 0.125)
    ow = int(H * 0.010)
    for cy, color in [(cx + gap, LAYER_LO),
                      (cx,       LAYER_MID),
                      (cx - gap, LAYER_HI)]:
        draw.polygon(rhombus(cx, cy, half_w, half_h),
                     fill=color, outline=OUTLINE, width=ow)

    hero = img.resize((240, 240), Image.LANCZOS)
    path = os.path.join(HERE, 'hero.png')
    hero.save(path)
    print('escrito', path)


def main():
    master = build_master()
    png_path = os.path.join(HERE, 'icon.png')
    master.save(png_path)
    print('escrito', png_path)

    build_hero()

    # Header pequeno (48px) para la GUI.
    header = master.resize((48, 48), Image.LANCZOS)
    header_path = os.path.join(HERE, 'logo_header.png')
    header.save(header_path)
    print('escrito', header_path)

    # ICO multi-size para Windows / el exe.
    ico_path = os.path.join(HERE, 'icon.ico')
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    master.save(ico_path, format='ICO', sizes=sizes)
    print('escrito', ico_path)


if __name__ == '__main__':
    main()
