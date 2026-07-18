from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from admin_import_sourcing_candidates import (  # noqa: E402
    EXPECTED_LEGACY_COUNT,
    build_import_payload,
    legacy_feature_to_rows,
    verify_remote,
)
from candidate_batches import load_candidate_batch_features  # noqa: E402


class SourcingImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.features = load_candidate_batch_features(ROOT / "public" / "import_queue.geojson")

    def test_complete_legacy_payload_preserves_parity(self) -> None:
        payload, quarantine = build_import_payload(self.features)
        linked_ids = [row["linked_venue_id"] for row in payload["candidates"]]
        self.assertEqual(EXPECTED_LEGACY_COUNT, len(self.features))
        self.assertEqual(EXPECTED_LEGACY_COUNT, len(payload["candidates"]))
        self.assertEqual([], quarantine)
        self.assertEqual(EXPECTED_LEGACY_COUNT, len(set(linked_ids)))
        self.assertEqual(linked_ids, [row["legacy_venue_id"] for row in payload["candidates"]])
        self.assertIn("venue_venue_i-flow.fr_i_arcueil", linked_ids)
        self.assertTrue(all(row["cockpit_visible"] for row in payload["candidates"]))
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in payload["candidates"]))

    def test_import_is_deterministic(self) -> None:
        first, first_quarantine = build_import_payload(self.features)
        second, second_quarantine = build_import_payload(json.loads(json.dumps(self.features)))
        self.assertEqual(first_quarantine, second_quarantine)
        self.assertEqual(first, second)

    def test_legacy_aliases_become_canonical_fields(self) -> None:
        rows = legacy_feature_to_rows(self.features[0], 1)
        candidate = rows["candidate"]
        properties = self.features[0]["properties"]
        self.assertEqual(properties["capacity_max_detected"], candidate["capacity_max"])
        self.assertEqual(properties["website"], candidate["website_url"])
        self.assertEqual(properties["contact"] or None, candidate["contact_text"])
        self.assertEqual("sourcing_idf", candidate["source_batch_key"])
        self.assertEqual(properties["rental_possible_status"], candidate["rental_status"])
        self.assertEqual(properties["actionability_score"], candidate["fit_score"])
        self.assertNotIn("capacity_max_detected", candidate)
        self.assertNotIn("website", candidate)
        self.assertNotIn("contact", candidate)

    def test_zero_capacity_and_coordinates_become_unknown(self) -> None:
        rows = legacy_feature_to_rows(self.features[1], 2)
        candidate = rows["candidate"]
        self.assertIsNone(candidate["capacity_max"])
        self.assertIsNone(candidate["lat"])
        self.assertIsNone(candidate["lon"])

    def test_import_creates_observations_evidence_and_events(self) -> None:
        rows = legacy_feature_to_rows(self.features[0], 1)
        self.assertEqual(rows["candidate"]["candidate_id"], rows["observation"]["candidate_id"])
        self.assertGreater(len(rows["evidence"]), 5)
        self.assertTrue(all(item["candidate_id"] == rows["candidate"]["candidate_id"] for item in rows["evidence"]))
        self.assertEqual("imported", rows["event"]["event_type"])
        self.assertEqual(rows["candidate"]["linked_venue_id"], rows["registry"]["venue_id"])

    def test_invalid_row_is_quarantined_without_hiding_valid_rows(self) -> None:
        malformed = {"type": "Feature", "geometry": None, "properties": {"name": "Sans identifiant"}}
        payload, quarantine = build_import_payload([self.features[0], malformed])
        self.assertEqual(1, len(payload["candidates"]))
        self.assertEqual(1, len(quarantine))
        self.assertIn("identifiant", quarantine[0]["error"])

    @patch("admin_import_sourcing_candidates.request")
    def test_remote_parity_keeps_terminal_legacy_candidates_registered(self, request_mock) -> None:
        request_mock.side_effect = [
            [{
                "candidate_id": "candidate-a",
                "legacy_venue_id": "legacy-a",
                "linked_venue_id": "canonical-a",
                "external_key": "legacy_candidate.legacy-a",
                "cockpit_visible": False,
            }],
            [{"venue_id": "legacy-a"}],
        ]
        verify_remote("https://example.supabase.co", "service-role-key", "campaign-a", {"legacy-a"})
        self.assertEqual(2, request_mock.call_count)


if __name__ == "__main__":
    unittest.main()
