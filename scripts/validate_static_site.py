#!/usr/bin/env python3
"""Validate the browser shell and the generated deployment directory."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
DEPLOY = ROOT / ".deploy-dist"
EXPECTED_DEPLOY_FILES = {
    "index.html",
    "runtime-config.js",
    "dataset-manifest.json",
    "salles_catalog_public.geojson",
    "css/cockpit.css",
    "js/cockpit.js",
}
FORBIDDEN_DEPLOY_NAMES = {
    "salles_all_idf.geojson",
    "salles_idf.geojson",
    "salles_small_idf.geojson",
    "import_queue.geojson",
    "funnel_debug.json",
    "venue_private_details.json",
    "private-manifest.json",
}


class ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.csp = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = values.get("content") or ""


def main() -> None:
    index = (PUBLIC / "index.html").read_text(encoding="utf-8")
    javascript = (PUBLIC / "js" / "cockpit.js").read_text(encoding="utf-8")
    parser = ShellParser()
    parser.feed(index)

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    assert not duplicates, f"IDs HTML dupliqués: {duplicates}"
    required_ids = set(re.findall(r"byId\(['\"]([^'\"]+)['\"]\)", javascript))
    missing = sorted(required_ids - set(parser.ids))
    assert not missing, f"IDs utilisés par JS mais absents du HTML: {missing}"
    assert "object-src 'none'" in parser.csp
    assert "https://*.supabase.co" in parser.csp
    assert "service_role" not in index.lower()
    assert "service_role" not in (PUBLIC / "runtime-config.js").read_text(encoding="utf-8").lower()
    assert "detectSessionInUrl: true" in javascript, (
        "Les liens d'invitation et de récupération Supabase doivent créer la session navigateur"
    )
    assert "resetPasswordForEmail" in javascript, (
        "Le formulaire doit permettre de redemander un lien si l'invitation a expiré"
    )
    assert "auth.updateUser({ password })" in javascript, (
        "Un membre invité doit pouvoir définir son mot de passe"
    )

    deployed = {
        path.relative_to(DEPLOY).as_posix()
        for path in DEPLOY.rglob("*")
        if path.is_file()
    }
    deployed_index = (DEPLOY / "index.html").read_text(encoding="utf-8")
    versioned_assets = {
        "runtime-config.js": "src",
        "js/cockpit.js": "src",
        "css/cockpit.css": "href",
    }
    for relative, attribute in versioned_assets.items():
        digest = hashlib.sha256((DEPLOY / relative).read_bytes()).hexdigest()[:16]
        expected_reference = f'{attribute}="{relative}?v={digest}"'
        assert expected_reference in deployed_index, (
            f"{relative} doit être référencé avec son empreinte de contenu"
        )
    assert deployed == EXPECTED_DEPLOY_FILES, (
        f"Allowlist de déploiement inattendue: {sorted(deployed)}"
    )
    assert not ({path.name for path in DEPLOY.rglob("*")} & FORBIDDEN_DEPLOY_NAMES)
    print(f"Site statique valide: {len(parser.ids)} IDs, {len(deployed)} fichiers publics")


if __name__ == "__main__":
    main()
