from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.routes.runeprofile import get_runeprofile_client
from app.config import Settings, get_settings
from app.main import create_app


class FakeRuneProfileClient:
    """In-memory stand-in for ``RuneProfileClient`` used in tests.

    Records every call and returns a small payload echoing the inputs so
    assertions can confirm the route forwarded the right arguments.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {"endpoint": name, "args": list(args), "kwargs": kwargs}

    async def get_summary(self, username: str) -> dict[str, Any]:
        if username.lower() == "ghost":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RuneProfile account not found",
            )
        return self._record("summary", username) | {
            "username": username,
            "skills": {"totalLevel": 1500, "totalXp": 12345678},
        }

    async def get_full_profile(self, username: str) -> dict[str, Any]:
        return self._record("full", username) | {"username": username}

    async def get_skills(self, username: str) -> dict[str, Any]:
        return self._record("skills", username)

    async def get_quests(self, username: str) -> dict[str, Any]:
        return self._record("quests", username)

    async def get_achievement_diaries(self, username: str) -> dict[str, Any]:
        return self._record("achievement_diaries", username)

    async def get_combat_achievements(self, username: str) -> dict[str, Any]:
        return self._record("combat_achievements", username)

    async def get_collection_log(self, username: str) -> dict[str, Any]:
        return self._record("collection_log", username)

    async def get_collection_log_tab(self, username: str, tab: str) -> dict[str, Any]:
        return self._record("collection_log_tab", username, tab)

    async def get_collection_log_page(self, username: str, tab: str, page: str) -> dict[str, Any]:
        return self._record("collection_log_page", username, tab, page)

    async def get_activities(
        self,
        username: str,
        *,
        cursor: str | None = None,
        direction: str | None = None,
        limit: int | None = None,
        activity_types: str | None = None,
    ) -> dict[str, Any]:
        return self._record(
            "activities",
            username,
            cursor=cursor,
            direction=direction,
            limit=limit,
            activity_types=activity_types,
        )


@pytest.fixture
def fake_client() -> FakeRuneProfileClient:
    return FakeRuneProfileClient()


@pytest.fixture
def rp_client(fake_client: FakeRuneProfileClient) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_runeprofile_client] = lambda: fake_client
    app.dependency_overrides[get_settings] = lambda: Settings(
        runeprofile_username="Zezima",
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_summary_returns_upstream_payload(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima")
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "Zezima"
    assert body["skills"]["totalLevel"] == 1500
    assert fake_client.calls == [("summary", ("Zezima",), {})]


def test_full_returns_upstream_payload(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/full")
    assert res.status_code == 200
    assert res.json()["username"] == "Zezima"
    assert fake_client.calls == [("full", ("Zezima",), {})]


def test_me_uses_configured_username(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get("/api/v1/runeprofile/me")
    assert res.status_code == 200
    assert res.json()["username"] == "Zezima"
    assert fake_client.calls == [("full", ("Zezima",), {})]


def test_me_503_when_username_not_configured(fake_client: FakeRuneProfileClient) -> None:
    app = create_app()
    app.dependency_overrides[get_runeprofile_client] = lambda: fake_client
    app.dependency_overrides[get_settings] = lambda: Settings(runeprofile_username=None)
    with TestClient(app) as c:
        res = c.get("/api/v1/runeprofile/me")
    assert res.status_code == 503


def test_summary_404_propagates(rp_client: TestClient) -> None:
    res = rp_client.get("/api/v1/runeprofile/ghost")
    assert res.status_code == 404
    assert res.json()["detail"] == "RuneProfile account not found"


def test_username_validation_rejects_bad_chars(rp_client: TestClient) -> None:
    res = rp_client.get("/api/v1/runeprofile/bad$name")
    assert res.status_code == 422


@pytest.mark.parametrize(
    ("path", "expected_call"),
    [
        ("skills", "skills"),
        ("quests", "quests"),
        ("achievement-diaries", "achievement_diaries"),
        ("combat-achievements", "combat_achievements"),
        ("collection-log", "collection_log"),
    ],
)
def test_simple_granular_endpoints(
    rp_client: TestClient,
    fake_client: FakeRuneProfileClient,
    path: str,
    expected_call: str,
) -> None:
    res = rp_client.get(f"/api/v1/runeprofile/Zezima/{path}")
    assert res.status_code == 200
    assert res.json()["endpoint"] == expected_call
    assert fake_client.calls == [(expected_call, ("Zezima",), {})]


def test_collection_log_tab(rp_client: TestClient, fake_client: FakeRuneProfileClient) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/collection-log/Bosses")
    assert res.status_code == 200
    assert fake_client.calls == [("collection_log_tab", ("Zezima", "Bosses"), {})]


def test_collection_log_page_handles_spaces(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/collection-log/Bosses/Abyssal%20Sire")
    assert res.status_code == 200
    assert fake_client.calls == [("collection_log_page", ("Zezima", "Bosses", "Abyssal Sire"), {})]


def test_activities_default_params(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/activities")
    assert res.status_code == 200
    assert fake_client.calls == [
        (
            "activities",
            ("Zezima",),
            {"cursor": None, "direction": None, "limit": None, "activity_types": None},
        )
    ]


def test_activities_forwards_query_params(
    rp_client: TestClient, fake_client: FakeRuneProfileClient
) -> None:
    res = rp_client.get(
        "/api/v1/runeprofile/Zezima/activities",
        params={
            "cursor": "abc123",
            "direction": "prev",
            "limit": 10,
            "activityTypes": "xp_milestone,quest_completed",
        },
    )
    assert res.status_code == 200
    assert fake_client.calls == [
        (
            "activities",
            ("Zezima",),
            {
                "cursor": "abc123",
                "direction": "prev",
                "limit": 10,
                "activity_types": "xp_milestone,quest_completed",
            },
        )
    ]


def test_activities_rejects_invalid_direction(rp_client: TestClient) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/activities", params={"direction": "sideways"})
    assert res.status_code == 422


def test_activities_rejects_out_of_range_limit(rp_client: TestClient) -> None:
    res = rp_client.get("/api/v1/runeprofile/Zezima/activities", params={"limit": 100})
    assert res.status_code == 422
