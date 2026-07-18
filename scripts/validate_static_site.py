#!/usr/bin/env python3
"""Validate the browser shell and the generated deployment directory."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from candidate_batches import batch_label, capacity_bucket, load_candidate_batch_features


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
    "js/sourcing-inbox.js",
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
    sourcing_javascript = (PUBLIC / "js" / "sourcing-inbox.js").read_text(encoding="utf-8")
    parser = ShellParser()
    parser.feed(index)

    duplicates = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    assert not duplicates, f"IDs HTML dupliqués: {duplicates}"
    required_ids = set(re.findall(
        r"byId\(['\"]([^'\"]+)['\"]\)",
        javascript + "\n" + sourcing_javascript,
    ))
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
    assert "auth.getUser()" in javascript and "AUTH_SESSION_INVALID" in javascript, (
        "Le bootstrap partagé doit valider la session auprès de Supabase"
    )
    assert "clearStoredAuthSession()" in javascript and "sessionStorage.removeItem" in javascript, (
        "Une session invalide doit être nettoyée uniquement dans l'onglet concerné"
    )

    assert "import_queue.geojson" in javascript and "mergeCandidateBatches" in javascript, (
        "Le cockpit authentifie doit restaurer les batchs candidats complets"
    )
    assert {"source-filter", "contact-filter", "qualification-filter"} <= set(parser.ids), (
        "Les batchs complets doivent rester triables dans le cockpit"
    )
    assert "candidateBatchKey" in javascript and "contactModeOf" in javascript, (
        "Les filtres de provenance et de joignabilite doivent etre actifs"
    )
    assert "CAMPAIGN_VENUE_MISMATCH" in javascript, (
        "Le cockpit doit refuser un espace partage incomplet plutot que perdre des appels"
    )
    assert "missingFollowups" in javascript and "SOURCING_PARITY_" in sourcing_javascript, (
        "La bascule Supabase doit conserver toutes les salles historiques visibles"
    )
    assert "root.SourcingInbox = api" in sourcing_javascript and "PAGE_SIZE = 100" in sourcing_javascript, (
        "La Sourcing Inbox doit etre chargeable et paginee cote serveur"
    )
    assert 'value="all" selected>Toutes les salles' in index, (
        "Le catalogue complet doit etre affiche par defaut"
    )
    candidates = load_candidate_batch_features(PUBLIC / "import_queue.geojson")
    candidate_ids = [feature["properties"]["candidate_id"] for feature in candidates]
    assert len(candidates) == 253, f"Batchs candidats incomplets: {len(candidates)}"
    assert len(candidate_ids) == len(set(candidate_ids))
    assert Counter(batch_label(feature) for feature in candidates) == {
        "sourcing_idf": 212,
        "banlieue_sud": 41,
    }
    assert Counter(capacity_bucket(feature) for feature in candidates) == {
        "unknown": 201,
        "small": 18,
        "over_20": 34,
    }
    assert Counter(
        str((feature.get("properties") or {}).get("rental_possible_status") or "")
        for feature in candidates
    ) == {"possible": 231, "unclear": 22}
    assert sum(
        bool((feature.get("properties") or {}).get("contact"))
        for feature in candidates
    ) == 113
    assert "venue_venue_i-flow.fr_i_arcueil" in candidate_ids

    deployed = {
        path.relative_to(DEPLOY).as_posix()
        for path in DEPLOY.rglob("*")
        if path.is_file()
    }
    deployed_index = (DEPLOY / "index.html").read_text(encoding="utf-8")
    versioned_assets = {
        "runtime-config.js": "src",
        "js/cockpit.js": "src",
        "js/sourcing-inbox.js": "src",
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
