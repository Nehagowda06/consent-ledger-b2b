import unittest

from core.system_lineage import canonical_json, compute_system_event_hash, verify_system_chain


class SystemLineageTests(unittest.TestCase):
    def test_deterministic_hashing(self) -> None:
        payload_a = {"b": 2, "a": 1}
        payload_b = {"a": 1, "b": 2}
        self.assertEqual(canonical_json(payload_a), canonical_json(payload_b))
        h1 = compute_system_event_hash("evt", "t1", "consent", "r1", payload_a, None)
        h2 = compute_system_event_hash("evt", "t1", "consent", "r1", payload_b, None)
        self.assertEqual(h1, h2)

    def test_reordering_failure(self) -> None:
        e1_hash = compute_system_event_hash("created", "t1", "consent", "r1", {"x": 1}, None)
        e2_hash = compute_system_event_hash("updated", "t1", "consent", "r1", {"x": 2}, e1_hash)
        ordered = [
            {
                "event_type": "created",
                "tenant_id": "t1",
                "resource_type": "consent",
                "resource_id": "r1",
                "payload": {"x": 1},
                "prev_hash": None,
                "event_hash": e1_hash,
            },
            {
                "event_type": "updated",
                "tenant_id": "t1",
                "resource_type": "consent",
                "resource_id": "r1",
                "payload": {"x": 2},
                "prev_hash": e1_hash,
                "event_hash": e2_hash,
            },
        ]
        self.assertTrue(verify_system_chain(ordered)["verified"])
        reordered = [ordered[1], ordered[0]]
        result = verify_system_chain(reordered)
        self.assertFalse(result["verified"])
        self.assertEqual(result["failure_index"], 0)

    def test_payload_tampering_detection(self) -> None:
        e1_hash = compute_system_event_hash("created", "t1", "consent", "r1", {"x": 1}, None)
        events = [
            {
                "event_type": "created",
                "tenant_id": "t1",
                "resource_type": "consent",
                "resource_id": "r1",
                "payload": {"x": 999},
                "prev_hash": None,
                "event_hash": e1_hash,
            }
        ]
        result = verify_system_chain(events)
        self.assertFalse(result["verified"])
        self.assertEqual(result["failure_index"], 0)
        self.assertIn("mismatch", result["failure_reason"])


if __name__ == "__main__":
    unittest.main()
