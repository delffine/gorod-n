"""Приглушить яркие цвета и подтянуть их к сепии фона.

    python scripts/sepia_tone.py <вход> <выход> [--sat 0.45] [--tint 0.35]
--sat  — сколько насыщенности оставить (0..1); --tint — доля сепии поверх (0..1).
"""
import argparse
import sys
from PIL import Image, ImageEnhance, ImageOps

p = argparse.ArgumentParser()
p.add_argument("src"); p.add_argument("dst")
p.add_argument("--sat", type=float, default=0.45)
p.add_argument("--tint", type=float, default=0.35)
a = p.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
im = Image.open(a.src).convert("RGB")
muted = ImageEnhance.Color(im).enhance(a.sat)
sepia = ImageOps.colorize(ImageOps.grayscale(im), black=(60, 40, 25), white=(250, 235, 205), mid=(190, 150, 105))
Image.blend(muted, sepia, a.tint).save(a.dst, quality=93)
print("Сохранено:", a.dst)
