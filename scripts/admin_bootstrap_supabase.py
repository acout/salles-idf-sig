#!/usr/bin/env python3
"""Upload a private release and initialize the shared Supabase workspace.

Required environment variables:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Missing users can be invited by email with ``--invite-missing``. No password or
service key is ever printed by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class ApiError(RuntimeError):
    pass


def request(
    base: str,
    key: str,
    method: str,
    path: str,
    body: Any | None = None,
    content_type: str = "application/json",
    extra_headers: dict[str, str] | None = None,
) -> Any:
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
        "Accept": "application/json",
    }
    headers.update(extra_headers or {})
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ApiError(f"API {method} {path}: HTTP {exc.code}: {detail}") from exc
    return json.loads(payload) if payload else None


def parse_member(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Format attendu: Nom=email@example.com")
    name, email = (part.strip() for part in value.split("=", 1))
    if not name or "@" not in email:
        raise argparse.ArgumentTypeError("Nom ou email invalide")
    return name, email.lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, type=parse_member, metavar="NOM=EMAIL")
    parser.add_argument("--member", action="append", default=[], type=parse_member, metavar="NOM=EMAIL")
    parser.add_argument("--campaign-name", default="Recherche urgente de salle")
    parser.add_argument("--event-date")
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--bucket", default="venue-datasets")
    parser.add_argument("--invite-missing", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def users_by_email(base: str, key: str) -> dict[str, dict[str, Any]]:
    response = request(base, key, "GET", "/auth/v1/admin/users?page=1&per_page=1000")
    users = response.get("users", response if isinstance(response, list) else [])
    return {str(user.get("email", "")).lower(): user for user in users if user.get("email")}


def ensure_users(base: str, key: str, requested: list[tuple[str, str]], invite_missing: bool) -> list[dict[str, str]]:
    known = users_by_email(base, key)
    members: list[dict[str, str]] = []
    for name, email in requested:
        user = known.get(email)
        if user is None:
            if not invite_missing:
                raise ApiError(f"Utilisateur absent: {email}. Relance avec --invite-missing ou crée-le dans Supabase Auth.")
            user = request(base, key, "POST", "/auth/v1/invite", {"email": email, "data": {"display_name": name}})
            print(f"Invitation envoyée: {email}")
        user_id = user.get("id")
        if not user_id:
            raise ApiError(f"Identifiant utilisateur absent pour {email}")
        members.append({"user_id": user_id, "display_name": name, "email": email})
    return members


def main() -> None:
    args = parse_args()
    base = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base.startswith("https://") or len(key) < 20:
        raise SystemExit("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requises")

    manifest_path = args.private_manifest.resolve()
    manifest = load_json(manifest_path)
    release_dir = manifest_path.parent
    overlay_artifact = next((item for item in manifest.get("artifacts", []) if item.get("path", "").endswith("/venue_private_details.json")), None)
    if overlay_artifact is None:
        raise SystemExit("venue_private_details.json absent du manifeste")
    overlay = load_json(release_dir / "venue_private_details.json")

    requested = [args.owner, *args.member]
    deduped: dict[str, tuple[str, str]] = {email: (name, email) for name, email in requested}
    members = ensure_users(base, key, list(deduped.values()), args.invite_missing)
    owner_email = args.owner[1]
    owner_id = next(member["user_id"] for member in members if member["email"] == owner_email)

    for artifact in manifest.get("artifacts", []):
        relative_remote = artifact["path"]
        local = release_dir / Path(relative_remote).name
        if not local.is_file():
            raise SystemExit(f"Artefact privé absent: {local}")
        encoded_path = urllib.parse.quote(relative_remote, safe="/")
        request(
            base,
            key,
            "POST",
            f"/storage/v1/object/{urllib.parse.quote(args.bucket, safe='')}/{encoded_path}",
            local.read_bytes(),
            "application/json" if local.suffix in {".json", ".geojson"} else "application/octet-stream",
            {"x-upsert": "true"},
        )
        print(f"Artefact privé chargé: {relative_remote}")

    result = request(
        base,
        key,
        "POST",
        "/rest/v1/rpc/admin_bootstrap_workspace",
        {
            "p_owner_user_id": owner_id,
            "p_members": members,
            "p_dataset_release_id": manifest["release_id"],
            "p_dataset_manifest_checksum": manifest["dataset_checksum"],
            "p_private_manifest": manifest,
            "p_venues": overlay["venues"],
            "p_campaign_name": args.campaign_name,
            "p_event_date": args.event_date,
        },
    )
    if not result or not result.get("ok"):
        raise ApiError(f"Initialisation refusée: {result}")
    print(f"Espace partagé prêt: campagne {result['campaign_id']}, {result['venue_count']} salles")


if __name__ == "__main__":
    try:
        main()
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
