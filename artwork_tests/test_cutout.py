"""Optional artwork QA: python3 -m unittest discover -s artwork_tests -v.

Requires Pillow. The standard-library-only package suite stays in tests/.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
ARTWORK = ROOT / 'artwork/xiaomi-2-pro'
MODEL = ROOT / 'models/xiaomi-2-pro'


class RegisteredCutoutTests(unittest.TestCase):
    def test_canvas_color_pixels_and_interior_alpha_are_unchanged(self):
        original = Image.open(ARTWORK / 'front-source.png').convert('RGBA')
        final = Image.open(MODEL / 'front.png').convert('RGBA')
        self.assertEqual(original.size, (724, 2172))
        self.assertEqual(final.size, original.size)
        self.assertIsNone(ImageChops.difference(original.convert('RGB'), final.convert('RGB')).getbbox())
        interior = (120, 126, 605, 2087)
        self.assertEqual(original.crop(interior).tobytes(), final.crop(interior).tobytes())

    def test_alpha_has_one_complete_smooth_silhouette_without_exterior_fragments(self):
        alpha = Image.open(MODEL / 'front.png').getchannel('A')
        self.assertEqual(alpha.getbbox(), (100, 106, 625, 2107))
        data = alpha.load()
        previous = None
        for y in range(106, 2107):
            xs = [x for x in range(alpha.width) if data[x, y] > 0]
            self.assertTrue(xs, f'Missing silhouette row {y}')
            self.assertEqual(xs, list(range(xs[0], xs[-1] + 1)), f'Detached fragment/hole at row {y}')
            if previous:
                self.assertLessEqual(abs(xs[0] - previous[0]), 4)
                self.assertLessEqual(abs(xs[-1] - previous[1]), 4)
            previous = xs[0], xs[-1]
        # Straight rails cannot develop spikes, notches or fringe.
        for y in range(125, 2088):
            self.assertEqual([data[x, y] for x in (99, 100, 101, 623, 624, 625)],
                             [0, 64, 255, 255, 80, 0])
        self.assertTrue(any(0 < data[x, 106] < 255 for x in range(100, 625)))

    def test_all_hotspot_coordinates_visible_bounds_and_hid_mappings_are_registered(self):
        recipe = json.loads((ARTWORK / 'cutout.json').read_text())
        layout = json.loads((MODEL / 'layout.json').read_text())
        geometry = {key: layout[key] for key in ('width', 'height', 'visible')}
        geometry['keys'] = [{'id': item['id'], 'shape': item['shape']} for item in layout['keys']]
        geometry['anchors'] = [{'capability': item['capability'], 'shape': item['shape']} for item in layout['anchors']]
        digest = hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, recipe['layoutGeometrySHA256'])
        self.assertEqual(hashlib.sha256((MODEL / 'inputs.json').read_bytes()).hexdigest(), recipe['inputsSHA256'])

    def test_cutout_is_reproducible_and_rejects_an_unregistered_source(self):
        spec = importlib.util.spec_from_file_location('clean_artwork', ROOT / 'scripts/clean_artwork.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        recipe = json.loads((ARTWORK / 'cutout.json').read_text())
        result = module.clean(ARTWORK / 'front-source.png', recipe)
        self.assertEqual(result.tobytes(), Image.open(MODEL / 'front.png').convert('RGBA').tobytes())
        recipe['sourceSHA256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            module.clean(ARTWORK / 'front-source.png', recipe)
