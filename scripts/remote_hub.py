#!/usr/bin/env python3
"""Validate and distribute v1/v2 remote packages and static subscription sources. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SOURCE_ID = 'infinite-remote-official'
SOURCE_NAME = {'en': 'Infinite Remote Hub', 'zh': '无限遥控器资源库'}


class InvalidPackage(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidPackage(message)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def text(value):
    return isinstance(value, str) and bool(value.strip())


def identifier(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def localized_text(value, version):
    if version == 1 and text(value):
        return len(value) <= 4096
    return (isinstance(value, dict) and text(value.get('en'))
            and all(text(language) and text(translation) and len(translation) <= 4096 for language, translation in value.items()))


def release_valid(value):
    return (isinstance(value, str) and RELEASE.fullmatch(value) is not None
            and all(len(part) <= 10 and int(part) <= 2 ** 32 - 1 for part in value.split('.')))


def action_valid(action, version=2):
    # Swift's synthesized enum Codable representation. No arbitrary executable descriptors.
    if not isinstance(action, dict) or len(action) != 1:
        return False
    name, payload = next(iter(action.items()))
    if version == 2 and name in {'openLink', 'chatBar', 'nextAgent'}:
        return False
    plain = {'openApp', 'chatBar', 'nextAgent', 'dictation', 'displaySleep', 'toggleDisplays',
             'appleMenu', 'lockScreen', 'showDesktop', 'volumeUp', 'volumeDown', 'mediaChooser', 'appSwitcher'}
    if name in plain:
        return payload == {} and isinstance(payload, dict)
    if not isinstance(payload, dict) or set(payload) != {'_0'}:
        return False
    value = payload['_0']
    if name == 'openLink':
        # Match app package safety policy: web links only, never shell/file/custom schemes.
        from urllib.parse import urlsplit
        if not text(value) or len(value) > 4096:
            return False
        try:
            link = urlsplit(value)
            return (link.scheme.lower() in ('http', 'https') and bool(link.hostname)
                    and link.username is None and link.password is None)
        except ValueError:
            return False
    if name == 'systemShortcut':
        return (isinstance(value, dict) and set(value) == {'keyCode', 'flags'}
                and integer(value.get('keyCode'), 0, 65535) and integer(value.get('flags'), 0, 2 ** 64 - 1))
    if name in ('shortcut', 'foregroundKey'):
        return (isinstance(value, dict) and set(value) == {'platform', 'keyCode', 'modifiers', 'keyName'}
                and value.get('platform') == 'macOS' and integer(value.get('keyCode'), 0, 65535)
                and text(value.get('keyName')) and len(value['keyName']) <= 64 and isinstance(value.get('modifiers'), list)
                and all(isinstance(v, str) and v in ('command', 'option', 'control', 'shift') for v in value['modifiers'])
                and len(set(value['modifiers'])) == len(value['modifiers']))
    return False


def validate_declarations(manifest, keys):
    key_ids = {key['id'] for key in keys}
    slots = key_ids | {key['id'] + suffix for key in keys
                       for flag, suffix in [('doublePress', '-double'), ('longPress', '-long')] if key.get(flag)}
    if manifest.get('target') is not None:
        target = manifest['target']
        require(isinstance(target, dict) and set(target) <= {'bundleID', 'path'}
                and isinstance(target.get('bundleID'), str) and len(target['bundleID']) <= 255
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]+', target['bundleID']) is not None
                and target.get('path') is None,
                'Invalid default application target')
    defaults = manifest.get('defaults', {})
    require(isinstance(defaults, dict) and all(slot in slots and action_valid(action, manifest['version'])
            for slot, action in defaults.items()), 'Invalid default action/slot')
    for key in keys:
        variants = [defaults.get(key['id'] + suffix) for suffix in ('-double', '-long')]
        require(not any(action == {'dictation': {}} for action in variants)
                and (defaults.get(key['id']) != {'dictation': {}} or all(action is None for action in variants)),
                'Dictation defaults cannot be combined with gesture defaults')
    behavior = manifest.get('behavior', {})
    allowed = {'coalescedKeys', 'deferredKeys', 'nativeDictationKeys', 'consumesContextMenu'}
    require(isinstance(behavior, dict) and set(behavior) <= allowed, 'Invalid behavior fields')
    for field in ('coalescedKeys', 'deferredKeys', 'nativeDictationKeys'):
        values = behavior.get(field, [])
        require(isinstance(values, list) and all(isinstance(value, str) and value in key_ids for value in values)
                and len(set(values)) == len(values), f'Invalid behavior keys: {field}')
    require(type(behavior.get('consumesContextMenu', False)) is bool, 'Invalid context-menu behavior')


def annotation_side(value):
    return value is None or (isinstance(value, str) and value in ('leading', 'trailing'))


def read_file(folder: Path, name: str, maximum=256 * 1024) -> bytes:
    require(isinstance(name, str) and text(name) and not name.startswith('.')
            and len(name.encode('utf-8')) <= 255 and ':' not in name
            and not any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in name)
            and '/' not in name and '\\' not in name, 'Resource must be a plain filename')
    path = folder / name
    require(not path.is_symlink() and path.is_file(), f'Not a regular resource: {name}')
    require(0 < path.stat().st_size <= maximum, f'Invalid resource size: {name}')
    return path.read_bytes()


def read_json(folder, name):
    def invalid_constant(value):
        raise InvalidPackage(f'Invalid JSON number: {value}')
    try:
        return json.loads(read_file(folder, name), parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise InvalidPackage(f'{name}: {error}') from error


def png_dimensions(data):
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'Artwork must be PNG')
    offset, dimensions, image_data, ended = 8, None, bytearray(), False
    palette = None
    while offset + 12 <= len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        require(end <= len(data), 'Truncated PNG chunk')
        payload = data[offset + 8:end - 4]
        crc = struct.unpack('>I', data[end - 4:end])[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == crc, 'Invalid PNG checksum')
        if dimensions is None:
            require(kind == b'IHDR' and length == 13, 'PNG must begin with IHDR')
            dimensions = struct.unpack('>II', payload[:8])
            depth, color, compression, filtering, interlace = payload[8:]
            legal_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            require(all(1 <= size <= 4096 for size in dimensions) and color in legal_depths
                    and depth in legal_depths[color] and compression == 0 and filtering == 0
                    and interlace in (0, 1), 'Invalid PNG header')
        elif kind == b'IHDR':
            raise InvalidPackage('Duplicate PNG header')
        if kind == b'acTL':
            raise InvalidPackage('Animated PNG is not a single image')
        if kind == b'IDAT':
            image_data.extend(payload)
        if kind == b'PLTE':
            require(palette is None and not image_data and 0 < length <= 768 and length % 3 == 0
                    and color not in (0, 4), 'Invalid PNG palette')
            palette = length // 3
        if kind == b'IEND':
            require(length == 0 and end == len(data), 'Invalid PNG end')
            ended = True
            break
        offset = end
    require(ended and image_data, 'Incomplete PNG')
    require(color != 3 or palette is not None and palette <= 2 ** depth, 'Missing or oversized PNG palette')
    width, height = dimensions
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if interlace == 0 else [
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    ]
    scanlines = []
    for x, y, step_x, step_y in passes:
        pass_width = max(0, (width - x + step_x - 1) // step_x)
        pass_height = max(0, (height - y + step_y - 1) // step_y)
        if pass_width and pass_height:
            row_bytes = (pass_width * channels * depth + 7) // 8
            scanlines.append((pass_width, pass_height, row_bytes))
    expected = sum(rows * (row_bytes + 1) for _, rows, row_bytes in scanlines)
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(image_data, expected + 1)
    except zlib.error as error:
        raise InvalidPackage('Invalid PNG image data') from error
    require(len(pixels) == expected and decoder.eof and not decoder.unused_data,
            'PNG scanline length does not match header')
    offset = 0
    for pass_width, rows, row_bytes in scanlines:
        previous = bytearray(row_bytes)
        for _ in range(rows):
            filter_type = pixels[offset]
            require(filter_type <= 4, 'Invalid PNG scanline filter')
            row = bytearray(pixels[offset + 1:offset + 1 + row_bytes])
            offset += row_bytes + 1
            if color == 3:
                # Palette images use one byte per filter pixel, including packed depths.
                for index in range(row_bytes):
                    left = row[index - 1] if index else 0
                    up = previous[index]
                    upper_left = previous[index - 1] if index else 0
                    if filter_type == 1: row[index] = (row[index] + left) & 255
                    elif filter_type == 2: row[index] = (row[index] + up) & 255
                    elif filter_type == 3: row[index] = (row[index] + (left + up) // 2) & 255
                    elif filter_type == 4:
                        estimate = left + up - upper_left
                        distances = [abs(estimate - value) for value in (left, up, upper_left)]
                        predictor = (left, up, upper_left)[distances.index(min(distances))]
                        row[index] = (row[index] + predictor) & 255
                mask = (1 << depth) - 1
                require(all(((row[(index * depth) // 8] >> (8 - depth - (index * depth) % 8)) & mask) < palette
                            for index in range(pass_width)), 'PNG pixel references missing palette color')
                previous = row
    return dimensions


def validate(folder: Path):
    require(folder.is_dir() and not folder.is_symlink(), 'Package must be a local directory')
    manifest = read_json(folder, 'manifest.json')
    require(isinstance(manifest, dict), 'Invalid manifest')
    version = manifest.get('version')
    require(type(version) is int and version in (1, 2)
            and identifier(manifest.get('id')) and localized_text(manifest.get('name'), version),
            'Invalid model identity/version/localization')
    if version == 2 or 'release' in manifest:
        require(release_valid(manifest.get('release')), 'Invalid package release')
    if version == 2 or 'summary' in manifest:
        require(localized_text(manifest.get('summary'), version), 'Invalid model summary/localization')
    if version == 2 or 'brand' in manifest:
        brand = manifest.get('brand')
        require(isinstance(brand, dict) and identifier(brand.get('id'))
                and localized_text(brand.get('name'), version), 'Invalid brand/localization')
        if brand.get('logo') is not None:
            dimensions = png_dimensions(read_file(folder, brand['logo'], 4 * 1024 * 1024))
            require(all(size <= 2048 for size in dimensions), 'Brand logo dimensions must not exceed 2048 pixels')
    devices = manifest.get('devices')
    require(isinstance(devices, list) and devices, 'Missing devices')
    require(all(isinstance(d, dict) and integer(d.get('vendor'), 1, 65535)
                and integer(d.get('product'), 1, 65535) for d in devices), 'Invalid HID device IDs')
    require(len({(d['vendor'], d['product']) for d in devices}) == len(devices), 'Duplicate device IDs')
    capabilities = manifest.get('capabilities')
    require(isinstance(capabilities, list) and all(isinstance(c, dict) and identifier(c.get('id'))
            and localized_text(c.get('name'), version) and isinstance(c.get('symbol'), str)
            and localized_text(c.get('description'), version)
            and (c.get('status') is None or localized_text(c['status'], version)) for c in capabilities), 'Invalid capabilities')
    cap_ids = {c['id'] for c in capabilities}
    require(len(cap_ids) == len(capabilities), 'Duplicate capabilities')

    layout = read_json(folder, 'layout.json')
    require(isinstance(layout, dict) and integer(layout.get('width'), 1, 4096)
            and integer(layout.get('height'), 1, 4096), 'Invalid image dimensions')
    visible = layout.get('visible')
    require(isinstance(visible, dict) and integer(visible.get('x'), 0, layout['width'] - 1)
            and integer(visible.get('y'), 0, layout['height'] - 1)
            and integer(visible.get('width'), 1, layout['width'] - visible['x'])
            and integer(visible.get('height'), 1, layout['height'] - visible['y']), 'Invalid visible bounds')

    def shape_valid(shape):
        if not isinstance(shape, dict) or shape.get('kind') not in ('ellipse', 'rectangle', 'sector'):
            return False
        if not all(type(shape.get(k)) in (int, float) and math.isfinite(shape[k]) for k in ('x', 'y', 'width', 'height')):
            return False
        if not all(shape.get(k) is None or type(shape[k]) in (int, float) and math.isfinite(shape[k])
                   for k in ('angle', 'innerRatio')):
            return False
        if shape['width'] <= 0 or shape['height'] <= 0:
            return False
        for axis, size in [('x', 'width'), ('y', 'height')]:
            lo = (shape[axis] - shape[size] / 2) * layout[size]
            hi = (shape[axis] + shape[size] / 2) * layout[size]
            if lo < visible[axis] or hi > visible[axis] + visible[size]:
                return False
        if shape['kind'] == 'sector':
            angle, inner = shape.get('angle'), shape.get('innerRatio')
            return (type(angle) in (int, float) and -360 <= angle <= 360
                    and type(inner) in (int, float) and 0 <= inner < 1)
        return True

    keys = layout.get('keys')
    require(isinstance(keys, list) and 1 <= len(keys) <= 128, 'Invalid keys')
    require(all(isinstance(k, dict) and identifier(k.get('id')) and localized_text(k.get('name'), version)
                and isinstance(k.get('symbol'), str) and shape_valid(k.get('shape'))
                and annotation_side(k.get('annotationSide'))
                and all(k.get(flag) is None or type(k[flag]) is bool for flag in ('doublePress', 'longPress'))
                for k in keys), 'Invalid key or hotspot')
    key_ids = {k['id'] for k in keys}
    require(len(key_ids) == len(keys), 'Duplicate key IDs')
    require(all(k['id'] + suffix not in key_ids for k in keys
                for flag, suffix in [('doublePress', '-double'), ('longPress', '-long')]
                if k.get(flag)), 'Action slot collides with a key ID')
    anchors = layout.get('anchors')
    require(isinstance(anchors, list) and all(isinstance(a, dict) and a.get('capability') in cap_ids
            and shape_valid(a.get('shape')) and annotation_side(a.get('annotationSide'))
            for a in anchors), 'Invalid capability anchor')
    require(len({a['capability'] for a in anchors}) == len(anchors), 'Duplicate anchors')

    validate_declarations(manifest, keys)

    inputs = read_json(folder, 'inputs.json')
    require(isinstance(inputs, list) and len(inputs) <= 512, 'Invalid inputs')
    previous = []
    for rule in inputs:
        require(isinstance(rule, dict) and rule.get('key') in key_ids
                and all(integer(rule.get(k), 0, 65535) for k in ('collectionPage', 'collectionUsage', 'page', 'usage'))
                and (rule.get('report') is None or integer(rule['report'], 0, 255))
                and (rule.get('value') is None or integer(rule['value'], -(2 ** 63), 2 ** 63 - 1))
                and (rule.get('acceptsArray') is None or type(rule['acceptsArray']) is bool), 'Invalid input reference/signal')
        require(rule.get('value') != 0 or (rule['page'] == 1 and rule['usage'] == 0x39), 'Inactive input value')
        require(not rule.get('acceptsArray') or rule['usage'] != 0, 'Invalid array usage')
        for other in previous:
            same_signal = all(rule[k] == other[k] for k in ('collectionPage', 'collectionUsage', 'page', 'usage'))
            reports_overlap = rule.get('report') is None or other.get('report') is None or rule['report'] == other['report']
            values_overlap = (rule.get('value') is None or other.get('value') is None
                              or rule['value'] == other['value'] or (rule.get('acceptsArray') and other.get('acceptsArray')))
            require(not (rule['key'] != other['key'] and same_signal and reports_overlap and values_overlap),
                    'A HID signal maps to multiple keys')
        previous.append(rule)
    image = read_file(folder, manifest.get('front'), 16 * 1024 * 1024)
    require(png_dimensions(image) == (layout['width'], layout['height']), 'PNG/layout dimensions differ')
    return manifest


def model_folders(root=ROOT):
    folders = sorted((root / 'models').iterdir())
    require(bool(folders), 'No model packages')
    device_ids, model_ids = set(), set()
    result = []
    for folder in folders:
        manifest = validate(folder)
        require(folder.name == manifest['id'] and manifest['id'] not in model_ids, 'Model folder/ID mismatch')
        model_ids.add(manifest['id'])
        for device in manifest['devices']:
            device_id = (device['vendor'], device['product'])
            require(device_id not in device_ids, 'Device IDs conflict across models')
            device_ids.add(device_id)
        result.append((folder, manifest))
    return result


def package_files(manifest):
    names = ['manifest.json', 'layout.json', 'inputs.json', manifest['front']]
    if manifest.get('brand', {}).get('logo') is not None:
        names.append(manifest['brand']['logo'])
    return sorted(set(names))


def hashes(folder, names):
    return {name: hashlib.sha256(read_file(folder, name, 16 * 1024 * 1024)).hexdigest() for name in sorted(names)}


def archive(folder, manifest):
    output = io.BytesIO()
    names = package_files(manifest) + ['metadata.json', 'README.zh.md', 'README.en.md', 'SOURCE.md']
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as zipped:
        for name in sorted(set(names)):
            data = read_file(folder, name, 16 * 1024 * 1024)
            entry = zipfile.ZipInfo(f"{manifest['id']}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            zipped.writestr(entry, data)
    return output.getvalue()


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_web(output, models):
    result = {'formatVersion': 2, 'id': SOURCE_ID, 'name': SOURCE_NAME, 'models': []}
    for folder, manifest in models:
        metadata = read_json(folder, 'metadata.json')
        require(isinstance(metadata, dict) and metadata.get('id') == manifest['id'], 'Invalid web metadata ID')
        for key in ('name', 'summary', 'setup', 'limitations'):
            require(isinstance(metadata.get(key), dict), f'Missing metadata: {key}')
            for language in ('zh', 'en'):
                value = metadata[key].get(language)
                require(text(value) if key in ('name', 'summary') else isinstance(value, list) and value and all(text(v) for v in value),
                        f'Missing {language} metadata: {key}')
        package = archive(folder, manifest)
        package_name = f"packages/{manifest['id']}.zip"
        write_atomic(output / package_name, package)
        preview = f"assets/{manifest['id']}/front.png"
        write_atomic(output / preview, read_file(folder, manifest['front'], 16 * 1024 * 1024))
        model = {**metadata, 'release': manifest.get('release', '0.0.0'), 'devices': manifest['devices'],
                 'preview': preview, 'package': package_name,
                 'packageSHA256': hashlib.sha256(package).hexdigest(),
                 'sourceSHA256': hashes(folder, package_files(manifest) + ['metadata.json', 'README.zh.md', 'README.en.md', 'SOURCE.md'])}
        if manifest['version'] == 2:
            model.update(name=manifest['name'], summary=manifest['summary'])
        if manifest.get('brand') is not None:
            model['brand'] = dict(manifest['brand'])
            if manifest['brand'].get('logo') is not None:
                logo = f"assets/{manifest['id']}/brand.png"
                write_atomic(output / logo, read_file(folder, manifest['brand']['logo'], 4 * 1024 * 1024))
                model['brand']['logo'] = logo
        result['models'].append(model)
    write_atomic(output / 'catalog.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())


def sync_app(app, models, write=False):
    require(not app.is_symlink(), 'App root must not be a symlink')
    app = app.resolve()
    require((app / 'Package.swift').is_file(), 'Explicit --app must point to the Swift application root')
    differences = []
    for folder, manifest in models:
        target = app / 'Sources/RemoteDesk/Resources/RemoteModels' / manifest['id']
        relative = target.relative_to(app)
        require(not any((app / Path(*relative.parts[:length])).is_symlink()
                        for length in range(1, len(relative.parts) + 1)), 'Sync target must not use symlink paths')
        names = package_files(manifest)
        require(not any((target / name).is_symlink() for name in names), 'Sync target resource must not be a symlink')
        changed = [name for name in names if not (target / name).is_file()
                   or (target / name).read_bytes() != (folder / name).read_bytes()]
        differences.extend(f"{manifest['id']}/{name}" for name in changed)
        if write and changed:
            target.mkdir(parents=True, exist_ok=True)
            backups = {name: (target / name).read_bytes() if (target / name).exists() else None for name in changed}
            try:
                for name in changed:
                    require(not (target / name).is_symlink(), 'Sync target resource must not be a symlink')
                    write_atomic(target / name, read_file(folder, name, 16 * 1024 * 1024))
            except BaseException:
                for name, backup in backups.items():
                    if backup is None:
                        (target / name).unlink(missing_ok=True)
                    else:
                        write_atomic(target / name, backup)
                raise
    return differences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('validate')
    pack = sub.add_parser('pack'); pack.add_argument('--output', type=Path, required=True)
    export = sub.add_parser('export-web', aliases=['export-source']); export.add_argument('--output', type=Path, required=True)
    sync = sub.add_parser('sync-app'); sync.add_argument('--app', type=Path, required=True); sync.add_argument('--write', action='store_true')
    args = parser.parse_args()
    try:
        models = model_folders()
        if args.command == 'pack':
            for folder, manifest in models:
                write_atomic(args.output / f"{manifest['id']}.zip", archive(folder, manifest))
        elif args.command in ('export-web', 'export-source'):
            export_web(args.output.resolve(), models)
        elif args.command == 'sync-app':
            differences = sync_app(args.app.resolve(), models, args.write)
            if differences and not args.write:
                print('Out of sync: ' + ', '.join(differences), file=sys.stderr)
                return 1
        print(f"{args.command}: OK ({len(models)} model)")
        return 0
    except (InvalidPackage, OSError, TypeError, KeyError, struct.error) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
