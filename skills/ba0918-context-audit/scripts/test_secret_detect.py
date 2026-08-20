#!/usr/bin/env python3
"""Unit tests for secret_detect.py.

Every sample secret is assembled by concatenation so the value never appears as a
literal in this source: the repository's secret scanning would flag it, and the
self-containment lint reads a rooted home path as an escape from the skill directory.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import secret_detect

SAMPLE_AWS = "AK" + "IA" + "IOSFODNN7" + "EXAMPLE"
SAMPLE_PEM = "-----BEGIN " + "PRIVATE KEY-----"
SAMPLE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM" + "." + "SflKxwRJSMeK"
SAMPLE_ANTHROPIC = "sk" + "-ant-" + ("A1b2c3" * 8)
SAMPLE_EMAIL = "alice" + "@" + "example.com"
SAMPLE_LINUX_HOME = ("/" + "home") + "/someuser"
SAMPLE_MACOS_HOME = ("/" + "Users") + "/someuser"
SAMPLE_ASSIGNMENT = "password" + " = " + '"' + "hunter2hunter2" + '"'
SAMPLE_LONG_QUOTED_KEY = '"' + ("A1b2c3d4" * 6) + '"'


class TestDetectSecrets(unittest.TestCase):
    def test_reports_an_aws_access_key_id(self):
        found = {f["type"] for f in secret_detect.detect_secrets(f"key {SAMPLE_AWS} end")}
        self.assertIn("aws_key", found)

    def test_reports_an_email_address(self):
        found = {f["type"] for f in secret_detect.detect_secrets(f"mail {SAMPLE_EMAIL}")}
        self.assertIn("email", found)

    def test_reports_nothing_for_prose_holding_no_secret(self):
        self.assertEqual(secret_detect.detect_secrets("just some normal prose here"), [])

    def test_a_kind_found_more_than_once_is_reported_once(self):
        found = secret_detect.detect_secrets(f"{SAMPLE_AWS} and again {SAMPLE_AWS}")
        self.assertEqual(found, [{"type": "aws_key", "masked": "[REDACTED:aws_key]"}])

    def test_every_finding_carries_its_kind_and_the_placeholder_it_masks_to(self):
        findings = secret_detect.detect_secrets(f"key {SAMPLE_AWS}")
        self.assertEqual(findings, [{"type": "aws_key", "masked": "[REDACTED:aws_key]"}])


class TestMaskProjectKey(unittest.TestCase):
    def test_a_key_beginning_at_the_operators_home_has_that_part_masked(self):
        key = "-".join(("", "home", "someone", "develop", "notes"))
        masked = secret_detect.mask_project_key(key)
        self.assertNotIn("someone", masked)
        self.assertTrue(masked.endswith("-develop-notes"), masked)

    def test_a_key_naming_no_home_is_returned_as_it_is(self):
        key = "-".join(("", "srv", "work", "notes"))
        self.assertEqual(secret_detect.mask_project_key(key), key)

    def test_a_home_root_appearing_later_in_a_key_is_not_masked(self):
        key = "-".join(("", "srv", "home", "someone", "notes"))
        self.assertEqual(secret_detect.mask_project_key(key), key)


class TestMaskSecrets(unittest.TestCase):
    def test_masks_an_aws_access_key_id(self):
        masked = secret_detect.mask_secrets(f"x {SAMPLE_AWS} y")
        self.assertNotIn(SAMPLE_AWS, masked)
        self.assertIn("[REDACTED:aws_key]", masked)

    def test_masks_a_pem_private_key_header(self):
        masked = secret_detect.mask_secrets(f"file starts {SAMPLE_PEM} body")
        self.assertNotIn("PRIVATE KEY", masked)
        self.assertIn("[REDACTED:private_key]", masked)

    def test_masks_a_jwt_including_its_signature_segment(self):
        masked = secret_detect.mask_secrets(f"auth {SAMPLE_JWT} end")
        self.assertNotIn("SflKxwRJSMeK", masked)
        self.assertIn("[REDACTED:jwt]", masked)

    def test_masks_a_known_prefix_credential_token(self):
        masked = secret_detect.mask_secrets(f"key {SAMPLE_ANTHROPIC} end")
        self.assertNotIn(SAMPLE_ANTHROPIC, masked)
        self.assertIn("[REDACTED:prefix_token]", masked)

    def test_detects_a_known_prefix_token_whether_or_not_it_is_quoted(self):
        bare = secret_detect.mask_secrets(f"value = {SAMPLE_ANTHROPIC}")
        quoted = secret_detect.mask_secrets('value = "' + SAMPLE_ANTHROPIC + '"')
        self.assertIn("[REDACTED:prefix_token]", bare)
        self.assertIn("[REDACTED:prefix_token]", quoted)

    def test_masks_an_email_address(self):
        masked = secret_detect.mask_secrets(f"mail {SAMPLE_EMAIL} end")
        self.assertNotIn(SAMPLE_EMAIL, masked)
        self.assertIn("[REDACTED:email]", masked)

    def test_masks_a_linux_home_directory_path(self):
        masked = secret_detect.mask_secrets(f"cwd {SAMPLE_LINUX_HOME} end")
        self.assertNotIn(SAMPLE_LINUX_HOME, masked)
        self.assertIn("[REDACTED:home_path]", masked)

    def test_masks_a_macos_home_directory_path(self):
        masked = secret_detect.mask_secrets(f"cwd {SAMPLE_MACOS_HOME} end")
        self.assertNotIn(SAMPLE_MACOS_HOME, masked)
        self.assertIn("[REDACTED:home_path]", masked)

    def test_masks_a_credential_assignment_naming_its_own_kind(self):
        masked = secret_detect.mask_secrets(f"config {SAMPLE_ASSIGNMENT} end")
        self.assertNotIn("hunter2hunter2", masked)
        self.assertIn("[REDACTED:generic_secret]", masked)

    def test_masks_a_long_quoted_key_carrying_no_recognisable_prefix(self):
        masked = secret_detect.mask_secrets(f"opaque {SAMPLE_LONG_QUOTED_KEY} end")
        self.assertNotIn(SAMPLE_LONG_QUOTED_KEY, masked)
        self.assertIn("[REDACTED:generic_long_key]", masked)

    def test_masking_an_already_masked_text_changes_nothing_further(self):
        once = secret_detect.mask_secrets(
            f"aws {SAMPLE_AWS} mail {SAMPLE_EMAIL} cwd {SAMPLE_LINUX_HOME}"
        )
        self.assertEqual(secret_detect.mask_secrets(once), once)

    def test_leaves_text_holding_no_secret_untouched(self):
        text = "no secrets in this line"
        self.assertEqual(secret_detect.mask_secrets(text), text)


if __name__ == "__main__":
    unittest.main()
