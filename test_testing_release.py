import unittest
from scripts.testing_release import resolve, REQUEST_PATH


class TestingReleaseTests(unittest.TestCase):
    request = {"branch": "testing/blackwidow-v4x-v3", "tag": "v0.4.2-test.2"}

    def test_matching_explicit_request_can_publish(self):
        self.assertTrue(resolve("refs/heads/testing/blackwidow-v4x-v3", "push", [REQUEST_PATH], self.request, "0.4.2-test.2")["enabled"])

    def test_main_pr_manual_and_ordinary_push_cannot_publish(self):
        for ref, event, changed in (("refs/heads/main", "push", [REQUEST_PATH]),
                                    ("refs/pull/1/merge", "pull_request", [REQUEST_PATH]),
                                    ("refs/heads/testing/blackwidow-v4x-v3", "workflow_dispatch", [REQUEST_PATH]),
                                    ("refs/heads/testing/blackwidow-v4x-v3", "push", ["README.md"])):
            self.assertFalse(resolve(ref, event, changed, self.request, "0.4.2-test.2")["enabled"])

    def test_another_branch_wrong_version_or_non_testing_tag_is_rejected(self):
        for changes in ({"branch": "testing/other"}, {"tag": "v0.4.2"}, {"tag": "v0.4.2-test.3"}, {"tag": "v0.4.2-test.2\nx=y"}):
            with self.assertRaises(ValueError):
                resolve("refs/heads/testing/blackwidow-v4x-v3", "push", [REQUEST_PATH], {**self.request, **changes}, "0.4.2-test.2")
