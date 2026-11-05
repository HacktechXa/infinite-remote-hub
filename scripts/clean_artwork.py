#!/usr/bin/env python3
"""Reproduce a pixel-registered cutout. Authoring only; requires Pillow.

RGB, canvas and interior alpha are retained. Only silhouette alpha is repaired.
The recipe belongs to the source artwork, never to the app renderer.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


def clean(source, recipe):
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != recipe['sourceSHA256']:
        raise ValueError('Source artwork checksum differs from the registered original')
    image = Image.open(source).convert('RGBA')
    if list(image.size) != recipe['canvas']:
        raise ValueError('Source canvas differs from the registered original')
    left, top, right, bottom = recipe['bounds']
    radius = recipe['radius']
    samples = recipe['samples']
    cx, cy = (left + right) / 2, (top + bottom) / 2
    half_width, half_height = (right - left) / 2 - radius, (bottom - top) / 2 - radius

    def distance(x, y):
        dx, dy = abs(x - cx) - half_width, abs(y - cy) - half_height
        return math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0) - radius

    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            d = distance(x + 0.5, y + 0.5)
            if d < -2:
                continue
            if d <= -1:
                alpha = 255
            elif d >= 1:
                alpha = 0
            else:
                covered = sum(distance(x + (sx + 0.5) / samples, y + (sy + 0.5) / samples) <= 0
                              for sy in range(samples) for sx in range(samples))
                alpha = round(255 * covered / samples ** 2)
            red, green, blue, _ = pixels[x, y]
            pixels[x, y] = red, green, blue, alpha
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    image = clean(args.source, json.loads(args.recipe.read_text()))
    image.save(args.output)
    print(f'Cleaned alpha only: {image.width} × {image.height}; {args.output}')


if __name__ == '__main__':
    main()
