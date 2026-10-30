"""Publication must require a matching tag or an explicit main-branch request."""
import unittest

from scripts.release_request import REQUEST_PATH, resolve_release


class ReleaseRequestTests(unittest.TestCase):
    def setUp(self):
        self.request = {"tag": "v0.4.0", "publish": True, "prerelease": True}

    def resolve(self, ref="refs/heads/main", event="push", changed=(REQUEST_PATH,), request=None):
        return resolve_release(ref, event, changed, self.request if request is None else request, "0.4.0")

    def test_explicit_main_request_selects_public_prerelease(self):
        result = self.resolve()
        self.assertTrue(result["enabled"])
        self.assertTrue(result["publish"])
        self.assertTrue(result["prerelease"])
        self.assertEqual(result["tag"], "v0.4.0")

    def test_ordinary_push_does_not_repeat_previous_release_request(self):
        self.assertFalse(self.resolve(changed=("README.md",))["enabled"])

    def test_pull_requests_and_feature_branches_cannot_request_publication(self):
        self.assertFalse(self.resolve(ref="refs/pull/2/merge", event="pull_request")["enabled"])
        self.assertFalse(self.resolve(ref="refs/heads/feature")["enabled"])

    def test_manual_main_build_does_not_publish(self):
        self.assertFalse(self.resolve(event="workflow_dispatch")["enabled"])

    def test_tag_build_keeps_existing_draft_behavior(self):
        result = self.resolve(ref="refs/tags/v0.4.0", changed=())
        self.assertTrue(result["enabled"])
        self.assertFalse(result["publish"])

    def test_mismatched_or_injected_tag_is_rejected(self):
        for tag in ("v0.3.0", "v0.4.0\npublish=true", "v0.4.0;echo", "0.4.0", 4):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.resolve(request={**self.request, "tag": tag})

    def test_publication_flags_require_boolean_values(self):
        for field in ("publish", "prerelease"):
            for value in ("false", 0, 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.resolve(request={**self.request, field: value})

    def test_missing_or_extra_fields_are_rejected(self):
        for request in ({}, {"tag": "v0.4.0"}, {**self.request, "target": "other"}):
            with self.assertRaises(ValueError): self.resolve(request=request)


if __name__ == "__main__":
    unittest.main()
