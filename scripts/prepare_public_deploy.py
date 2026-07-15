#!/usr/bin/env python3
"""Create an allowlisted static deployment directory.

Never deploy ``public/`` directly: that directory still contains legacy source
artifacts kept for reproducibility. This script copies only browser-safe files.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".deploy-dist"
ALLOWLIST = (
    "index.html",
    "runtime-config.js",
    "dataset-manifest.json",
    "salles_catalog_public.geojson",
    "css/cockpit.css",
    "js/cockpit.js",
)
FORBIDDEN_NAMES = {
    "salles_all_idf.geojson",
    "import_queue.geojson",
    "funnel_debug.json",
    "venue_private_details.json",
    "private-manifest.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "public")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise SystemExit("Le dossier de déploiement doit être séparé de public/")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for relative in ALLOWLIST:
        src = source / relative
        if not src.is_file():
            raise SystemExit(f"Fichier public requis absent: {relative}")
        dst = output / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    index_path = output / "index.html"
    index = index_path.read_text(encoding="utf-8")
    versioned_assets = {
        "runtime-config.js": "src",
        "js/cockpit.js": "src",
        "css/cockpit.css": "href",
    }
    for relative, attribute in versioned_assets.items():
        digest = hashlib.sha256((output / relative).read_bytes()).hexdigest()[:16]
        pattern = rf'{attribute}="{re.escape(relative)}(?:\?v=[^"]*)?"'
        replacement = f'{attribute}="{relative}?v={digest}"'
        index, count = re.subn(pattern, replacement, index)
        if count != 1:
            raise SystemExit(f"Référence {relative} unique absente de index.html")
    index_path.write_text(
        index,
        encoding="utf-8",
        newline="\n",
    )

    deployed = {path.name for path in output.rglob("*") if path.is_file()}
    leaked = sorted(deployed & FORBIDDEN_NAMES)
    if leaked:
        raise SystemExit(f"Artefacts privés détectés: {', '.join(leaked)}")
    print(f"Déploiement public prêt: {len(ALLOWLIST)} fichiers dans {output}")


if __name__ == "__main__":
    main()
