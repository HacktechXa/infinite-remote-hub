import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/remote_hub.py'
spec = importlib.util.spec_from_file_location('hub', SCRIPT)
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
SOURCE = SCRIPT.parents[1] / 'models/xiaomi-2-pro'
LEGACY = SCRIPT.parents[1] / 'tests/fixtures/v1/xiaomi-2-pro'


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'xiaomi-2-pro'
        shutil.copytree(SOURCE, self.folder)

    def edit(self, filename, update):
        path = self.folder / filename
        value = json.loads(path.read_text())
        update(value)
        path.write_text(json.dumps(value))

    def test_existing_model_has_expected_identity_and_dimensions(self):
        manifest = hub.validate(self.folder)
        self.assertEqual(manifest['id'], 'xiaomi-2-pro')
        self.assertEqual(manifest['devices'], [{'vendor': 0x2717, 'product': 0x32B8}])
        self.assertEqual(hub.png_dimensions((self.folder / 'front.png').read_bytes()), (724, 2172))

    def test_optional_presentation_fields_validate_and_legacy_packages_remain_readable(self):
        original = json.loads((self.folder / 'layout.json').read_text())
        for value in ('leading', 'trailing', None):
            layout = copy.deepcopy(original)
            layout['keys'][0]['annotationSide'] = value
            layout['anchors'][0]['annotationSide'] = value
            (self.folder / 'layout.json').write_text(json.dumps(layout))
            hub.validate(self.folder)
        for value in ('left', '', True, 1, [], {}):
            for collection in ('keys', 'anchors'):
                layout = copy.deepcopy(original)
                layout[collection][0]['annotationSide'] = value
                (self.folder / 'layout.json').write_text(json.dumps(layout))
                with self.assertRaises(hub.InvalidPackage):
                    hub.validate(self.folder)
        for collection in ('keys', 'anchors'):
            for item in original[collection]:
                item.pop('annotationSide', None)
        (self.folder / 'layout.json').write_text(json.dumps(original))
        manifest = json.loads((self.folder / 'manifest.json').read_text())
        for capability in manifest['capabilities']:
            capability.pop('status', None)
        (self.folder / 'manifest.json').write_text(json.dumps(manifest))
        hub.validate(self.folder)

    def test_capability_status_is_optional_but_must_be_nonempty_text(self):
        original = json.loads((self.folder / 'manifest.json').read_text())
        for value in ({'en': 'Hardware present', 'zh': '硬件具备'}, None, '', '  ', True, 12, [], {}, {'zh': '硬件具备'}, {'en': ' '}):
            manifest = copy.deepcopy(original)
            manifest['capabilities'][0]['status'] = value
            (self.folder / 'manifest.json').write_text(json.dumps(manifest))
            if value is None or isinstance(value, dict) and value.get('en', '').strip():
                hub.validate(self.folder)
            else:
                with self.assertRaisesRegex(hub.InvalidPackage, 'capabilities'):
                    hub.validate(self.folder)

    def test_immutable_v1_fixture_remains_readable(self):
        manifest = hub.validate(LEGACY)
        self.assertEqual(manifest['version'], 1)
        self.assertIsInstance(manifest['name'], str)
        self.assertNotIn('release', manifest)
        self.assertNotIn('defaults', manifest)
        self.assertNotIn('behavior', manifest)
        self.assertNotIn('brand', manifest)

    def test_v2_upgrade_preserves_device_artwork_hid_and_geometry(self):
        old = hub.validate(LEGACY)
        new = hub.validate(self.folder)
        self.assertEqual(new['version'], 2)
        for field in ('id', 'devices', 'front'):
            self.assertEqual(new[field], old[field])
        for name in ('front.png', 'inputs.json'):
            self.assertEqual((LEGACY / name).read_bytes(), (self.folder / name).read_bytes())
        old_layout = json.loads((LEGACY / 'layout.json').read_text())
        new_layout = json.loads((self.folder / 'layout.json').read_text())
        self.assertEqual({key['id']: key['name']['en'] for key in new_layout['keys'] if key['id'] in ('ok', 'plus', 'minus')},
                         {'ok': 'OK', 'plus': 'Vol +', 'minus': 'Vol −'})
        self.assertEqual(new['release'], '0.0.1')
        for key in new_layout['keys']:
            self.assertEqual(set(key['name']), {'en', 'zh'})
            key['name'] = key['name']['zh']
        self.assertEqual(new_layout, old_layout)
        self.assertEqual(new['brand']['name'], {'en': 'Xiaomi', 'zh': '小米'})
        self.assertEqual(hub.hashes(self.folder, ['brand.png'])['brand.png'],
                         'cbd7602e878c987180cbb14e86aa241541e3523e85362e1ac0bc7b896f93ea65')
        self.assertEqual(hub.png_dimensions((self.folder / 'brand.png').read_bytes()), (196, 196))

    def test_v2_required_localized_fields_need_nonempty_english(self):
        manifest_path = self.folder / 'manifest.json'
        original = manifest_path.read_bytes()
        updates = [lambda m: m.update(name='Legacy string'), lambda m: m.update(summary={'zh': '概要'}),
                   lambda m: m.pop('brand'), lambda m: m['brand'].update(name={'en': ''}),
                   lambda m: m['capabilities'][0].update(name='Legacy capability'),
                   lambda m: m['capabilities'][0].update(description={'en': ' '})]
        for update in updates:
            with self.subTest(update=update):
                manifest_path.write_bytes(original)
                self.edit('manifest.json', update)
                with self.assertRaises(hub.InvalidPackage):
                    hub.validate(self.folder)
        manifest_path.write_bytes(original)
        self.edit('layout.json', lambda layout: layout['keys'][0].update(name={'zh': '电源'}))
        with self.assertRaisesRegex(hub.InvalidPackage, 'key or hotspot'):
            hub.validate(self.folder)

    def test_release_is_required_for_v2_and_a_strict_numeric_triplet(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        for value in (None, '1', '1.0', '1.0.0-beta', '01.0.0', '-1.0.0', '1.0.0.0', True, '4294967296.0.0', '9' * 5000 + '.0.0'):
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m.update(release=value))
            with self.subTest(value=value), self.assertRaisesRegex(hub.InvalidPackage, 'release'):
                hub.validate(self.folder)
        for value in ('0.0.0', '1.2.3', '4294967295.0.0'):
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m.update(release=value))
            self.assertEqual(hub.validate(self.folder)['release'], value)
        path.write_bytes(original)
        self.edit('manifest.json', lambda m: m.update(version=3))
        with self.assertRaisesRegex(hub.InvalidPackage, 'version'):
            hub.validate(self.folder)

    def test_default_actions_and_behavior_may_be_omitted(self):
        self.edit('manifest.json', lambda m: (m.pop('defaults'), m.pop('behavior'), m.pop('target')))
        hub.validate(self.folder)

    def test_default_action_slots_values_and_dictation_gestures_are_validated(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        invalid = [
            {'missing': {'openApp': {}}}, {'minus-long': {'openApp': {}}},
            {'power': {'runScript': {'_0': 'do something'}}}, {'power': {'openApp': {'unexpected': True}}},
            {'power': {'openLink': {'_0': 'file:///tmp/example'}}},
            {'power': {'openLink': {'_0': 'https://user:pass@example.com'}}},
            {'power': {'foregroundKey': {'_0': {'platform': 'Windows', 'keyCode': 126, 'modifiers': [], 'keyName': 'Up'}}}},
            {'power': {'systemShortcut': {'_0': {'keyCode': 65536, 'flags': 0}}}},
            {'power-long': {'dictation': {}}},
            {'power': {'dictation': {}}, 'power-long': {'lockScreen': {}}},
        ]
        for value in invalid:
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m.update(defaults=value))
            with self.subTest(value=value), self.assertRaises(hub.InvalidPackage):
                hub.validate(self.folder)
        valid = {'power': {'openApp': {}},
                 'power-long': {'systemShortcut': {'_0': {'keyCode': 65535, 'flags': 2**64-1}}}}
        path.write_bytes(original)
        self.edit('manifest.json', lambda m: m.update(defaults=valid))
        hub.validate(self.folder)
        self.assertFalse(hub.action_valid({'shortcut': {'_0': {'platform': 'macOS', 'keyCode': True, 'modifiers': [], 'keyName': 'A'}}}))
        self.assertFalse(hub.action_valid({'shortcut': {'_0': {'platform': 'macOS', 'keyCode': 1, 'modifiers': ['shift', 'shift'], 'keyName': 'A'}}}))

    def test_v2_defaults_reject_runner_unsupported_actions_without_changing_v1_reading(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        actions = ({'openLink': {'_0': 'https://example.com/path'}}, {'chatBar': {}}, {'nextAgent': {}})
        for action in actions:
            path.write_bytes(original)
            self.edit('manifest.json', lambda manifest: manifest.update(defaults={'power': action}))
            with self.subTest(action=action), self.assertRaisesRegex(hub.InvalidPackage, 'default action'):
                hub.validate(self.folder)
            legacy = json.loads((LEGACY / 'manifest.json').read_text())
            legacy['defaults'] = {'power': action}
            path.write_text(json.dumps(legacy))
            self.assertEqual(hub.validate(self.folder)['version'], 1)

    def test_behavior_requires_unique_declared_physical_keys_and_boolean_flags(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        for value in ({'coalescedKeys': ['missing']}, {'deferredKeys': ['power-long']},
                      {'nativeDictationKeys': ['voice', 'voice']}, {'consumesContextMenu': 1},
                      {'coalescedKeys': 'home'}, {'unknown': []}, []):
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m.update(behavior=value))
            with self.subTest(value=value), self.assertRaisesRegex(hub.InvalidPackage, 'behavior'):
                hub.validate(self.folder)

    def test_brand_logo_requires_a_safe_regular_png(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        for value in ('../brand.png', '/brand.png', 'folder/brand.png', 'file:brand.png', 'bad\n.png'):
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m['brand'].update(logo=value))
            with self.subTest(value=value), self.assertRaisesRegex(hub.InvalidPackage, 'filename'):
                hub.validate(self.folder)
        path.write_bytes(original)
        (self.folder / 'brand.png').write_bytes(b'not png')
        with self.assertRaisesRegex(hub.InvalidPackage, 'PNG'):
            hub.validate(self.folder)
        (self.folder / 'brand.png').unlink()
        (self.folder / 'brand.png').symlink_to(SOURCE / 'brand.png')
        with self.assertRaisesRegex(hub.InvalidPackage, 'regular resource'):
            hub.validate(self.folder)

    def test_brand_logo_dimensions_match_app_limit_for_both_axes(self):
        def png(width, height):
            def chunk(kind, payload):
                return (struct.pack('>I', len(payload)) + kind + payload
                        + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))
            return (b'\x89PNG\r\n\x1a\n'
                    + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(bytes((width * 4 + 1) * height)))
                    + chunk(b'IEND', b''))
        for width, height in ((3000, 1), (1, 3000)):
            image = png(width, height)
            self.assertEqual(hub.png_dimensions(image), (width, height))
            (self.folder / 'brand.png').write_bytes(image)
            with self.subTest(width=width, height=height), self.assertRaisesRegex(hub.InvalidPackage, '2048'):
                hub.validate(self.folder)
        for width, height in ((2048, 1), (1, 2048)):
            (self.folder / 'brand.png').write_bytes(png(width, height))
            hub.validate(self.folder)

    def test_default_target_is_a_bundle_id_without_executable_path(self):
        path = self.folder / 'manifest.json'
        original = path.read_bytes()
        for value in ({'bundleID': ''}, {'bundleID': 'a'}, {'bundleID': 'com.example/app'},
                      {'bundleID': 'com.example.app', 'path': '/tmp/executable'}, {'bundleID': True}, []):
            path.write_bytes(original)
            self.edit('manifest.json', lambda m: m.update(target=value))
            with self.subTest(value=value), self.assertRaisesRegex(hub.InvalidPackage, 'target'):
                hub.validate(self.folder)

    def test_missing_input_key_and_conflicting_signal_are_rejected(self):
        path = self.folder / 'inputs.json'
        original = json.loads(path.read_text())
        invalid = copy.deepcopy(original)
        invalid[0]['key'] = 'missing'
        path.write_text(json.dumps(invalid))
        with self.assertRaisesRegex(hub.InvalidPackage, 'reference'):
            hub.validate(self.folder)
        other = copy.deepcopy(original[0])
        other['key'] = 'voice' if other['key'] != 'voice' else 'power'
        path.write_text(json.dumps(original + [other]))
        with self.assertRaisesRegex(hub.InvalidPackage, 'multiple keys'):
            hub.validate(self.folder)

    def test_dimensions_and_out_of_bounds_hotspot_are_rejected(self):
        layout_path = self.folder / 'layout.json'
        original = layout_path.read_bytes()
        self.edit('layout.json', lambda layout: layout.update(width=725))
        with self.assertRaisesRegex(hub.InvalidPackage, 'dimensions differ'):
            hub.validate(self.folder)
        layout_path.write_bytes(original)
        self.edit('layout.json', lambda layout: layout['keys'][0]['shape'].update(x=-1))
        with self.assertRaisesRegex(hub.InvalidPackage, 'hotspot'):
            hub.validate(self.folder)

    def test_path_traversal_resource_symlink_and_folder_symlink_are_rejected(self):
        manifest_path = self.folder / 'manifest.json'
        original = manifest_path.read_bytes()
        self.edit('manifest.json', lambda value: value.update(front='../front.png'))
        with self.assertRaisesRegex(hub.InvalidPackage, 'filename'):
            hub.validate(self.folder)
        manifest_path.write_bytes(original)
        (self.folder / 'front.png').unlink()
        (self.folder / 'front.png').symlink_to(SOURCE / 'front.png')
        with self.assertRaisesRegex(hub.InvalidPackage, 'regular resource'):
            hub.validate(self.folder)
        linked = self.root / 'linked'
        linked.symlink_to(SOURCE, target_is_directory=True)
        with self.assertRaisesRegex(hub.InvalidPackage, 'directory'):
            hub.validate(linked)

    def test_corrupted_png_and_nonfinite_json_are_rejected(self):
        image = bytearray((self.folder / 'front.png').read_bytes())
        image[24] ^= 1
        (self.folder / 'front.png').write_bytes(image)
        with self.assertRaisesRegex(hub.InvalidPackage, 'checksum'):
            hub.validate(self.folder)
        shutil.copy2(SOURCE / 'front.png', self.folder / 'front.png')
        path = self.folder / 'layout.json'
        path.write_text(path.read_text().replace('"x": 0.315', '"x": NaN'))
        with self.assertRaisesRegex(hub.InvalidPackage, 'JSON number'):
            hub.validate(self.folder)

    def test_png_scanlines_filters_header_and_interlace_are_validated(self):
        def png(width, height, pixels, depth=8, color=6, interlace=0, palette=None):
            def chunk(kind, data):
                return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
            result = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace))
            if palette is not None: result += chunk(b'PLTE', palette)
            return result + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
        with self.assertRaisesRegex(hub.InvalidPackage, 'scanline length'):
            hub.png_dimensions(png(724, 2172, b'\0'))
        with self.assertRaisesRegex(hub.InvalidPackage, 'scanline filter'):
            hub.png_dimensions(png(1, 1, b'\x05\0\0\0\0'))
        with self.assertRaisesRegex(hub.InvalidPackage, 'header'):
            hub.png_dimensions(png(1, 1, b'\0\0\0\0\0', depth=3))
        self.assertEqual(hub.png_dimensions(png(1, 1, b'\0\0\0\0\0')), (1, 1))
        self.assertEqual(hub.png_dimensions(png(1, 1, b'\0\0\0\0\0', interlace=1)), (1, 1))
        # Seven Adam7 passes, with empty passes omitted for the small image.
        passes = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
        pixels = b''
        for x, y, dx, dy in passes:
            width, height = max(0, (3-x+dx-1)//dx), max(0, (3-y+dy-1)//dy)
            if width and height: pixels += bytes((width*4+1)*height)
        self.assertEqual(hub.png_dimensions(png(3, 3, pixels, interlace=1)), (3, 3))
        with self.assertRaisesRegex(hub.InvalidPackage, 'palette color'):
            hub.png_dimensions(png(1, 1, b'\0\x80', depth=1, color=3, palette=b'\0\0\0'))
        self.assertEqual(hub.png_dimensions(png(1, 1, b'\0\0', depth=1, color=3, palette=b'\0\0\0')), (1, 1))

    def test_input_values_match_swift_int64_range(self):
        path = self.folder / 'inputs.json'
        original = json.loads(path.read_text())
        for value in (-(2**63), 2**63-1):
            changed = copy.deepcopy(original); changed[0]['value'] = value
            path.write_text(json.dumps(changed))
            self.assertEqual(hub.validate(self.folder)['id'], 'xiaomi-2-pro')
        for value in (-(2**63)-1, 2**63, True):
            changed = copy.deepcopy(original); changed[0]['value'] = value
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(hub.InvalidPackage, 'reference/signal'):
                hub.validate(self.folder)

    def test_optional_double_fields_are_typed_for_every_shape(self):
        path = self.folder / 'layout.json'
        original = json.loads(path.read_text())
        for field in ('angle', 'innerRatio'):
            for value in ('not-a-number', True, []):
                changed = copy.deepcopy(original); changed['keys'][0]['shape'][field] = value
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(hub.InvalidPackage, 'hotspot'):
                    hub.validate(self.folder)
            for value in (None, 0.5):
                changed = copy.deepcopy(original); changed['keys'][0]['shape'][field] = value
                path.write_text(json.dumps(changed))
                self.assertEqual(hub.validate(self.folder)['id'], 'xiaomi-2-pro')
    def test_invalid_sector_and_capability_reference_are_rejected(self):
        path = self.folder / 'layout.json'
        original = path.read_bytes()
        self.edit('layout.json', lambda layout: layout['keys'][2]['shape'].update(innerRatio=1))
        with self.assertRaisesRegex(hub.InvalidPackage, 'hotspot'):
            hub.validate(self.folder)
        path.write_bytes(original)
        self.edit('layout.json', lambda layout: layout['anchors'][0].update(capability='missing'))
        with self.assertRaisesRegex(hub.InvalidPackage, 'anchor'):
            hub.validate(self.folder)

    def test_duplicate_ids_boolean_device_ids_and_action_collisions_are_rejected(self):
        original = (self.folder / 'manifest.json').read_bytes()
        self.edit('manifest.json', lambda value: value['devices'][0].update(vendor=True))
        with self.assertRaisesRegex(hub.InvalidPackage, 'device IDs'):
            hub.validate(self.folder)
        (self.folder / 'manifest.json').write_bytes(original)
        path = self.folder / 'layout.json'
        original = path.read_bytes()
        self.edit('layout.json', lambda value: value['keys'].append(value['keys'][0]))
        with self.assertRaisesRegex(hub.InvalidPackage, 'Duplicate key'):
            hub.validate(self.folder)
        path.write_bytes(original)
        def collision(value):
            key = copy.deepcopy(value['keys'][0])
            key['id'] += '-long'
            value['keys'].append(key)
        self.edit('layout.json', collision)
        with self.assertRaisesRegex(hub.InvalidPackage, 'slot collides'):
            hub.validate(self.folder)

    def test_zip_is_deterministic_and_round_trips_to_readable_package(self):
        manifest = hub.validate(self.folder)
        first = hub.archive(self.folder, manifest)
        self.assertEqual(first, hub.archive(self.folder, manifest))
        destination = self.root / 'unpacked'
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertTrue(all(name.startswith('xiaomi-2-pro/') and '..' not in name for name in archive.namelist()))
            archive.extractall(destination)
        restored = destination / 'xiaomi-2-pro'
        self.assertEqual(hub.validate(restored), manifest)
        self.assertEqual(hub.hashes(restored, hub.package_files(manifest)), hub.hashes(self.folder, hub.package_files(manifest)))

    def test_web_export_includes_bilingual_content_and_verifiable_hashes(self):
        output = self.root / 'web'
        models = [(self.folder, hub.validate(self.folder))]
        hub.export_web(output, models)
        catalog = json.loads((output / 'catalog.json').read_text())
        model = catalog['models'][0]
        self.assertEqual(catalog['formatVersion'], 2)
        self.assertEqual(catalog['id'], 'infinite-remote-official')
        self.assertEqual(set(catalog['name']), {'en', 'zh'})
        self.assertEqual(model['release'], '0.0.1')
        self.assertEqual(model['brand']['id'], 'xiaomi')
        for path in (model['preview'], model['brand']['logo'], model['package']):
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn('..', Path(path).parts)
            self.assertTrue((output / path).is_file())
        self.assertEqual((output / model['brand']['logo']).read_bytes(), (self.folder / 'brand.png').read_bytes())
        self.assertEqual(set(model['name']), {'zh', 'en'})
        self.assertEqual(model['sourceSHA256']['inputs.json'], hub.hashes(self.folder, ['inputs.json'])['inputs.json'])
        self.assertEqual(model['packageSHA256'], hub.hashlib.sha256((output / model['package']).read_bytes()).hexdigest())
        before = (output / 'catalog.json').read_bytes()
        hub.export_web(output, models)
        self.assertEqual(before, (output / 'catalog.json').read_bytes())

    def test_cli_exports_independent_source_and_zip_with_identical_assets(self):
        output = self.root / 'source'
        result = subprocess.run([sys.executable, str(SCRIPT), 'export-source', '--output', str(output)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = json.loads((output / 'catalog.json').read_text())
        model = catalog['models'][0]
        before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        result = subprocess.run([sys.executable, str(SCRIPT), 'export-web', '--output', str(output)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()})
        unpacked = self.root / 'extracted'
        with zipfile.ZipFile(output / model['package']) as archive:
            self.assertTrue(all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist()))
            self.assertTrue(all(entry.external_attr >> 16 == 0o100644 for entry in archive.infolist()))
            archive.extractall(unpacked)
        folder = unpacked / model['id']
        manifest = hub.validate(folder)
        self.assertEqual(manifest['release'], model['release'])
        self.assertEqual((folder / manifest['front']).read_bytes(), (output / model['preview']).read_bytes())
        self.assertEqual((folder / manifest['brand']['logo']).read_bytes(), (output / model['brand']['logo']).read_bytes())
        self.assertTrue(all(isinstance(model[key][language], list)
                            for key in ('setup', 'limitations') for language in ('en', 'zh')))

    def test_sync_checks_before_writing_and_does_not_touch_unrelated_resources(self):
        app = self.root / 'app'
        app.mkdir()
        (app / 'Package.swift').write_text('// fixture')
        target = app / 'Sources/RemoteDesk/Resources/RemoteModels/xiaomi-2-pro'
        target.mkdir(parents=True)
        (target / 'local.txt').write_text('preserve')
        models = [(self.folder, hub.validate(self.folder))]
        self.assertEqual(len(hub.sync_app(app, models)), 5)
        self.assertFalse((target / 'manifest.json').exists())
        hub.sync_app(app, models, write=True)
        self.assertEqual(hub.sync_app(app, models), [])
        self.assertEqual((target / 'local.txt').read_text(), 'preserve')
        self.assertFalse((target / 'metadata.json').exists())

    def test_sync_write_failure_rolls_back_and_rejects_linked_resources(self):
        app = self.root / 'app'; app.mkdir(); (app / 'Package.swift').write_text('// fixture')
        models = [(self.folder, hub.validate(self.folder))]
        hub.sync_app(app, models, write=True)
        target = app / 'Sources/RemoteDesk/Resources/RemoteModels/xiaomi-2-pro'
        names = hub.package_files(models[0][1])
        for name in names: (target / name).write_bytes(b'previous ' + name.encode())
        before = {name: (target / name).read_bytes() for name in names}
        write = hub.write_atomic
        calls = 0
        def interrupted(path, data):
            nonlocal calls
            calls += 1
            if calls == 3: raise OSError('simulated write interruption')
            return write(path, data)
        with patch.object(hub, 'write_atomic', interrupted):
            with self.assertRaisesRegex(OSError, 'interruption'):
                hub.sync_app(app, models, write=True)
        self.assertEqual(before, {name: (target / name).read_bytes() for name in names})
        external = self.root / 'external.png'; external.write_bytes(b'outside')
        (target / 'front.png').unlink(); (target / 'front.png').symlink_to(external)
        with self.assertRaisesRegex(hub.InvalidPackage, 'symlink'):
            hub.sync_app(app, models, write=True)
        self.assertEqual(external.read_bytes(), b'outside')


if __name__ == '__main__':
    unittest.main()
