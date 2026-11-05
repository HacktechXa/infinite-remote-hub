# Infinite Remote Hub

[中文版本](README.zh-CN.md)

The independent remote-adaptation library for Infinite Remote. The first supported model is the Xiaomi Bluetooth Remote 2 Pro. New adapters use package format v2, with English/Chinese copy, brand artwork, explicit defaults and behavior. The validator also accepts legacy v1 packages. The tools require Python 3.10 or later and use only the Python standard library.

The GitHub repository is `HacktechXa/infinite-remote-hub`.

## Commands

```sh
python3 scripts/remote_hub.py validate
python3 scripts/remote_hub.py pack --output dist
python3 -m unittest discover -s tests -v
```

A ZIP contains one model folder with manifest/layout/input JSON, its front PNG, an optional brand PNG and guides. New app installations have no bundled remotes. Install Xiaomi from the resource library or import the ZIP directly. Updates require a higher release owned by the same source; another source cannot replace an installed model. Existing user mappings remain separate. `metadata.json` supplies bilingual setup and limitations for the source and website.

## Explicit Synchronization

```sh
# Compare only; exits with status 1 when differences exist. The caller supplies the path.
python3 scripts/remote_hub.py sync-app --app /absolute/path/to/app
# Legacy explicit resource-copy utility; do not use it to rebundle models in production.
python3 scripts/remote_hub.py sync-app --app /absolute/path/to/app --write
# Export a self-contained source (catalog.json, packages/, assets/).
python3 scripts/remote_hub.py export-source --output /absolute/path/to/source
# The same exporter can produce an independent website snapshot.
python3 scripts/remote_hub.py export-web --output /absolute/path/to/website/public/hub
```

Do not connect the repositories through symlinks, submodules, or implicit sibling paths. After updating a model, validate and test it first, then synchronize explicitly and inspect the target repository's diff. Packaging fixes order, timestamps, and permissions so identical content produces identical SHA256 hashes. Referenced resources reject symlinks and path traversal. Export is local and explicit; it never publishes or creates a remote. The official subscription URL is `https://raw.githubusercontent.com/HacktechXa/infinite-remote-hub/main/catalog.json`; publication is a separate authorized operation: verify the export, commit and push catalog.json/packages/assets to the public hub repository, then check the public index and package hashes. A local export alone is not proof that the subscription is live. See [PROTOCOL.md](PROTOCOL.md) for exact package and source contracts.

## Model Guides and Provenance

`models/xiaomi-2-pro/` contains Chinese and English guides plus `SOURCE.md`. [ADAPTING.md](ADAPTING.md) describes how to add a model, and [HARDWARE-TEST-TEMPLATE.md](HARDWARE-TEST-TEMPLATE.md) records physical-device testing.

Device artwork, source records, and third-party materials retain their original licenses and provenance. The project license does not replace or expand those rights.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HacktechXa/infinite-remote-hub&type=Date)](https://star-history.com/#HacktechXa/infinite-remote-hub&Date)

## License

Copyright (C) 2026 Infinite Remote contributors.

This project is licensed under the [GNU General Public License, version 3 or (at your option) any later version](LICENSE) (`GPL-3.0-or-later`). Commercial use is permitted. When distributing the software or a derivative work, you must comply with the GPL's corresponding-source and same-license requirements.
