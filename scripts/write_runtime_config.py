#!/usr/bin/env python3
"""Write the public runtime configuration from deployment environment values."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "public" / "runtime-config.js")
    parser.add_argument("--mode", choices=("read_only", "shared"), default=os.getenv("APP_MODE", "read_only"))
    parser.add_argument("--app-release", default=os.getenv("APP_RELEASE", "local"))
    parser.add_argument("--supabase-url", default=os.getenv("SUPABASE_URL", ""))
    parser.add_argument("--supabase-anon-key", default=os.getenv("SUPABASE_ANON_KEY", ""))
    parser.add_argument("--private-bucket", default=os.getenv("SUPABASE_PRIVATE_BUCKET", "venue-datasets"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "shared":
        parsed = urlparse(args.supabase_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise SystemExit("SUPABASE_URL HTTPS est requise en mode shared")
        if len(args.supabase_anon_key.strip()) < 20:
            raise SystemExit("SUPABASE_ANON_KEY est requise en mode shared")

    config = {
        "mode": args.mode,
        "appRelease": args.app_release,
        "clientContractVersion": 2,
        "supabaseUrl": args.supabase_url.strip(),
        "supabaseAnonKey": args.supabase_anon_key.strip(),
        "privateBucket": args.private_bucket.strip(),
    }
    payload = "window.SALLES_CONFIG = Object.freeze(" + json.dumps(config, ensure_ascii=False, separators=(",", ":")) + ");\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(f"Configuration {args.mode} écrite dans {args.output}")


if __name__ == "__main__":
    main()
