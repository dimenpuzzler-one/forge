import json
import unittest

from forge_core.errors import SourceError
from forge_sources.skills_sh import SkillsShAdapter


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, headers, timeout):
        self.urls.append((url, headers, timeout))
        return self.responses.pop(0)


class SkillsShAdapterContractTests(unittest.TestCase):
    def test_list_payload_maps_to_stable_metadata(self) -> None:
        body = json.dumps(
            {
                "data": [
                    {
                        "id": "acme/skills/postgres",
                        "slug": "postgres",
                        "name": "Postgres",
                        "source": "acme/skills",
                        "installs": 12,
                        "sourceType": "github",
                        "installUrl": "https://github.com/acme/skills",
                        "url": "https://skills.sh/acme/skills/postgres",
                    }
                ],
                "pagination": {"page": 0, "perPage": 100, "total": 1, "hasMore": False},
            }
        ).encode()
        adapter = SkillsShAdapter(transport=FakeTransport([(200, {}, body)]), token="test")

        page = adapter.list_skills(page=0)

        self.assertFalse(page.has_more)
        self.assertEqual("acme/skills/postgres", page.entries[0].id)
        self.assertIn("per_page=500", adapter.transport.urls[0][0])

    def test_rate_limit_retries_with_retry_after(self) -> None:
        success = json.dumps({"data": [], "pagination": {"page": 0, "hasMore": False}}).encode()
        sleeps = []
        adapter = SkillsShAdapter(
            transport=FakeTransport([(429, {"Retry-After": "0"}, b"{}"), (200, {}, success)]),
            token="test",
            sleep=sleeps.append,
        )

        adapter.list_skills(page=0)

        self.assertEqual([0.0], sleeps)

    def test_auth_error_explains_next_action(self) -> None:
        adapter = SkillsShAdapter(transport=FakeTransport([(401, {}, b'{"message":"Unauthorized"}')]), token=None)

        with self.assertRaisesRegex(SourceError, "VERCEL_OIDC_TOKEN"):
            adapter.list_skills(page=0)
