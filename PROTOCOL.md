# Model packages and static sources

New models use protocol v2. `validate` accepts protocol 1 and 2; unknown versions fail. A protocol version describes the schema; `release` describes a model revision and must be a canonical `major.minor.patch` numeric triplet, without leading zeros. Components fit unsigned 32-bit integers. A legacy v1 package may omit release and is treated by the app as `0.0.0`.

## Package v2

The ZIP has exactly one root folder named for the stable model ID. `manifest.json`, `layout.json`, `inputs.json` and the referenced PNG front are required. Optional brand PNG, metadata and guides travel with the package. Resource names are plain filenames, never absolute paths, nested paths or symlinks. JSON is limited to 256 KiB per file, front PNG to 16 MiB and logo PNG to 4 MiB. Images are validated single-frame PNGs. Front images allow dimensions from 1 to 4096 and must match the layout dimensions. Each brand logo dimension must be from 1 to 2048.

```json
{
  "version": 2,
  "id": "example-remote",
  "release": "1.0.0",
  "name": {"en": "Example Remote", "zh": "示例遥控器"},
  "summary": {"en": "A supported remote.", "zh": "已适配的遥控器。"},
  "brand": {"id": "example", "name": {"en": "Example"}, "logo": "brand.png"},
  "devices": [{"vendor": 1234, "product": 5678}],
  "front": "front.png",
  "capabilities": [],
  "target": {"bundleID": "com.example.app"},
  "defaults": {"power": {"toggleDisplays": {}}},
  "behavior": {"deferredKeys": ["power"], "consumesContextMenu": false}
}
```

`name`, `summary`, brand name, every key name, capability name/description and any capability status are localized objects with a nonblank `en` and optional nonblank translations such as `zh`, at most 4096 characters each. The app resolves the requested language then English. Legacy v1 string values remain readable verbatim. IDs and HID rules never depend on displayed language.

`layout.keys` retain their existing geometry/symbol/gesture fields; `annotationSide` is optional (`leading`/`trailing`). Capability anchors reference declared IDs. Gestures create `key-double` and `key-long` action slots only where the key declares that gesture. Slots cannot collide with physical key IDs.

`defaults` and `behavior` are optional and default to empty declarations. Defaults may reference only declared action slots. Actions use Swift AgentAction Codable JSON, never executable scripts. The v2 no-payload allowlist is openApp, dictation, displaySleep, toggleDisplays, appleMenu, lockScreen, showDesktop, volumeUp, volumeDown, mediaChooser and appSwitcher. Each is represented as `{ "caseName": {} }`.

Associated-value cases use `{ "caseName": { "_0": value } }`:

- `shortcut` / `foregroundKey`: `{ "platform": "macOS", "keyCode": 126, "modifiers": [], "keyName": "↑" }`; keyCode is UInt16, modifiers are unique command/option/control/shift strings.
- `systemShortcut`: `{ "keyCode": 126, "flags": 0 }`; flags is UInt64.
`openLink`, `chatBar` and `nextAgent` are rejected in new v2 package defaults because the application runner does not implement these actions. Legacy v1 decoding remains compatible; accepting legacy data does not add action execution support.

Optional `target` is an AppTarget object with an alphanumeric/dot/hyphen bundleID (2–255 characters, beginning with an alphanumeric character); path must be omitted or null. It supplies the initial target for default actions; it does not execute an application during validation or install.

Behavior arrays `coalescedKeys`, `deferredKeys`, `nativeDictationKeys` contain distinct physical key IDs, never gesture slots. `consumesContextMenu` is Boolean. Unknown behavior fields and unsupported default actions fail. Dictation cannot occupy a double/long slot; when the primary action is dictation, gesture defaults for that key must be absent. Model-specific behavior belongs here; engine runtime logic reads declarations. Xiaomi legacy fallback exists only in the v1 compatibility reader.

## Static subscription / website export

`export-source --output PATH` and its `export-web` alias write the same independent snapshot. It contains `catalog.json`, `packages/<id>.zip` and `assets/<id>/front.png` plus optional `brand.png`. All catalog resource paths are relative to catalog.json; ZIP manifest paths stay local filenames. No build reads sibling repositories and no command publishes automatically.

The catalog is `{ "formatVersion": 2, "id": "infinite-remote-official", "name": {"en":"Infinite Remote Hub","zh":"无限遥控器资源库"}, "models": [...] }`. Each entry contains id, release, localized name/summary/brand, devices, preview, package and packageSHA256. `sourceSHA256` remains a filename-to-SHA256 dictionary for website compatibility. Bilingual setup/limitations come from model metadata and remain arrays of strings. Exported brand logo paths refer to exported assets, rather than the package filename. Entries use stable folder order; ZIPs use sorted names, fixed timestamps and Unix file permissions, with no host-specific metadata.

The official URL is `https://raw.githubusercontent.com/szhjia/infinite-remote-hub/main/catalog.json`. Export locally, verify the generated catalog, packages and assets, then commit and push those files to the public hub repository in a separately authorized publication step. Verify the public index and package hashes after publication. Generating a local export alone does not make it available there. The app verifies download hashes and package identity/release, rejects source ownership changes and device conflicts, and allows updates only to a higher release from the same owner. User mappings are stored separately. Installed packages work offline.

## Compatibility and verification

The immutable v1 package fixture under `tests/fixtures/v1/` verifies legacy parsing independently of the v2 maintained model. Source-copy `sync-app --app PATH` is retained as a legacy explicit developer tool, including referenced logos; it is not used to bundle real models into production. Install through a source or local ZIP instead.

After implementation and test authoring, run `python3 scripts/remote_hub.py validate`, `python3 -m unittest discover -s tests -v`, and deterministic export/ZIP roundtrips. Optional artwork QA has separate Pillow dependencies. Record actual physical hardware coverage in HARDWARE-TEST-TEMPLATE.md; tooling checks do not prove physical device behavior.

## Independent model releases

Each model maintains its own semantic `release`, independent of the app and of other models. Xiaomi Bluetooth Remote 2 Pro starts its public release line at `0.0.1`. Protocol `version` remains `2`; it is not the model release. GitHub release tags use `<model-id>/v<release>` (for example `xiaomi-2-pro/v0.0.1`).
