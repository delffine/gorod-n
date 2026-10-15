"""Перекрасить яркие цвета картинки в палитру её же неба (облаков).

    python scripts/recolor_to_sky.py <вход> <выход> [--sky 0,0,1920,200] [--strength 1.0]
Палитра берётся из прямоугольника --sky: каждой яркости ставится в соответствие средний цвет
неба той же яркости. Перекрашиваются только насыщенные пиксели с оттенком, далёким от неба.
"""
import argparse
import sys

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
p = argparse.ArgumentParser()
p.add_argument("src"); p.add_argument("dst")
p.add_argument("--sky", default="0,0,1920,200")
p.add_argument("--strength", type=float, default=1.0)
a = p.parse_args()

img = np.asarray(Image.open(a.src).convert("RGB")).astype(np.float32)
lum = img @ np.array([0.299, 0.587, 0.114], np.float32)
x0, y0, x1, y1 = map(int, a.sky.split(","))
sky, sky_l = img[y0:y1, x0:x1].reshape(-1, 3), lum[y0:y1, x0:x1].ravel()

# таблица яркость → средний цвет неба; пустые ячейки заполняем интерполяцией
lut = np.full((256, 3), np.nan, np.float32)
for v in range(256):
    m = np.abs(sky_l - v) < 3
    if m.sum() > 20:
        lut[v] = sky[m].mean(0)
idx = np.arange(256); ok = ~np.isnan(lut[:, 0])
for c in range(3):
    lut[:, c] = np.interp(idx, idx[ok], lut[ok, c])
# для яркостей вне диапазона неба: тёмные — затемнённый самый тёмный тон, светлые — к бумаге
lo, hi = idx[ok][0], idx[ok][-1]
lut[:lo] = lut[lo] * (idx[:lo, None] / max(lo, 1))
lut[hi:] = lut[hi] + (np.array([250, 240, 220]) - lut[hi]) * ((idx[hi:, None] - hi) / max(255 - hi, 1))

target = lut[np.clip(lum, 0, 255).astype(int)]
sat = (img.max(2) - img.min(2)) / (img.max(2) + 1)
# перекрашиваем только оттенки, далёкие от тёплого тона неба (синий, бирюза, красный);
# серое, бумага, лицо, пальто и золото остаются как есть
hue = np.asarray(Image.fromarray(img.astype(np.uint8)).convert("HSV"))[..., 0].astype(np.float32) * 360 / 255
sky_hue = np.median(hue[y0:y1, x0:x1])
hd = np.abs((hue - sky_hue + 180) % 360 - 180)
w = np.clip((hd - 15) / 30, 0, 1) * np.clip((sat - 0.08) / 0.15, 0, 1) * a.strength
out = img * (1 - w[..., None]) + target * w[..., None]
Image.fromarray(out.clip(0, 255).astype(np.uint8)).save(a.dst, quality=95)
print("Сохранено:", a.dst)
