import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.assertion_crypto import canonical_assertion_payload, sign_assertion, verify_assertion_signature
from core.canonical import canonical_json, canonical_json_bytes
from core.delegation_crypto import canonical_delegation_message, sign_delegation, verify_delegation
from core.lineage import canonical_json as lineage_canonical_json
from core.lineage_signing import sign_bytes, verify_bytes
from core.system_lineage import canonical_json as system_canonical_json


def _keypair_hex() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_key_hex = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    public_key_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return public_key_hex, private_key_hex


class DeterminismInvariantTests(unittest.TestCase):
    def test_canonical_json_is_identical_across_crypto_modules(self) -> None:
        payload = {"z": [3, 2, 1], "a": {"b": 1, "c": "x"}, "u": "mu"}
        expected = canonical_json(payload)
        self.assertEqual(expected, lineage_canonical_json(payload))
        self.assertEqual(expected, system_canonical_json(payload))
        self.assertEqual(canonical_json_bytes(payload), expected.encode("utf-8"))
        self.assertEqual(canonical_assertion_payload(payload), expected.encode("utf-8"))

    def test_ed25519_signatures_are_deterministic_and_backend_consistent(self) -> None:
        public_key_hex, private_key_hex = _keypair_hex()
        message = canonical_json_bytes({"k": "v", "n": 1})
        sig_a = sign_assertion(private_key_hex, message)
        sig_b = sign_bytes(private_key_hex, message)
        sig_c = sign_delegation(private_key_hex, message)
        self.assertEqual(sig_a, sig_b)
        self.assertEqual(sig_b, sig_c)
        self.assertTrue(verify_assertion_signature(public_key_hex, message, sig_a))
        self.assertTrue(verify_bytes(public_key_hex, message, sig_b))
        self.assertTrue(verify_delegation(public_key_hex, message, sig_c))

    def test_signature_verification_rejects_tampering_deterministically(self) -> None:
        public_key_hex, private_key_hex = _keypair_hex()
        message = canonical_json_bytes({"k": "v", "n": 1})
        signature = sign_bytes(private_key_hex, message)
        tampered_message = canonical_json_bytes({"k": "v", "n": 2})
        tampered_signature = ("f" if signature[0] != "f" else "e") + signature[1:]
        self.assertFalse(verify_bytes(public_key_hex, tampered_message, signature))
        self.assertFalse(verify_bytes(public_key_hex, message, tampered_signature))

    def test_delegation_message_canonicalization_is_stable(self) -> None:
        msg1 = canonical_delegation_message("b", "a", "rotation")
        msg2 = canonical_delegation_message("b", "a", "rotation")
        self.assertEqual(msg1, msg2)


if __name__ == "__main__":
    unittest.main()
