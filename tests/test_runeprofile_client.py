from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.services.runeprofile import RuneProfileClient, RuneProfileError, TTLCache


def make_client(handler: httpx.MockTransport) -> RuneProfileClient:
    """Build a client whose underlying httpx uses an in-memory transport."""
    client = RuneProfileClient(
        base_url="https://api.runeprofile.com/v1",
        api_key="test-key",
        user_agent="the-irons-backend (test)",
    )
    # Swap the transport for one that records and answers locally.
    client._client = httpx.AsyncClient(
        base_url="https://api.runeprofile.com/v1",
        headers={
            "Accept": "application/json",
            "User-Agent": "the-irons-backend (test)",
            "X-API-Key": "test-key",
        },
        transport=handler,
    )
    return client


@pytest.mark.asyncio
async def test_path_segments_are_url_encoded() -> None:
    received: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(httpx.MockTransport(respond))
    try:
        await client.get_collection_log_page("Cool Guy", "Bosses", "Abyssal Sire")
    finally:
        await client.aclose()

    assert len(received) == 1
    request = received[0]
    # raw_path is bytes and preserves on-the-wire URL-encoding (`.path` decodes).
    assert request.url.raw_path == (b"/v1/accounts/Cool%20Guy/collection-log/Bosses/Abyssal%20Sire")
    assert request.headers["X-API-Key"] == "test-key"
    assert request.headers["User-Agent"] == "the-irons-backend (test)"


@pytest.mark.asyncio
async def test_activities_query_params_are_forwarded() -> None:
    received: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"activities": []})

    client = make_client(httpx.MockTransport(respond))
    try:
        await client.get_activities(
            "Zezima",
            cursor="abc",
            direction="prev",
            limit=5,
            activity_types="xp_milestone,quest_completed",
        )
    finally:
        await client.aclose()

    request = received[0]
    params: dict[str, Any] = dict(request.url.params)
    assert params == {
        "cursor": "abc",
        "direction": "prev",
        "limit": "5",
        "activityTypes": "xp_milestone,quest_completed",
    }


@pytest.mark.asyncio
async def test_404_translates_to_runeprofile_error() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Account not found"})

    client = make_client(httpx.MockTransport(respond))
    try:
        with pytest.raises(RuneProfileError) as excinfo:
            await client.get_summary("nobody")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_429_translates_to_runeprofile_error() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Too many requests"})

    client = make_client(httpx.MockTransport(respond))
    try:
        with pytest.raises(RuneProfileError) as excinfo:
            await client.get_summary("anyone")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 429


@pytest.mark.asyncio
async def test_timeout_translates_to_504() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = make_client(httpx.MockTransport(respond))
    try:
        with pytest.raises(RuneProfileError) as excinfo:
            await client.get_summary("anyone")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 504


# ---------------------------------------------------------------------------
# TTLCache unit tests
# ---------------------------------------------------------------------------


class TestTTLCache:
    def test_set_and_get(self) -> None:
        cache = TTLCache(default_ttl=60.0)
        cache.set("k", {"data": 1})
        assert cache.get("k") == {"data": 1}

    def test_missing_key_returns_none(self) -> None:
        cache = TTLCache()
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self) -> None:
        cache = TTLCache(default_ttl=0.0)
        cache.set("k", "val", ttl=0.0)
        # time.monotonic() will have advanced past ttl=0
        assert cache.get("k") is None

    def test_clear(self) -> None:
        cache = TTLCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_evict_expired(self) -> None:
        cache = TTLCache(default_ttl=60.0)
        cache.set("alive", "yes", ttl=9999)
        # Force an already-expired entry by writing the expiry timestamp directly.
        cache._store["dead"] = (0.0, "no")
        cache.evict_expired()
        assert cache.get("alive") == "yes"
        assert cache.get("dead") is None


# ---------------------------------------------------------------------------
# Client-level caching tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_returns_cached_without_http() -> None:
    call_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"skills": {"totalLevel": 2277}})

    client = make_client(httpx.MockTransport(respond))
    try:
        r1 = await client.get_summary("Zezima")
        r2 = await client.get_summary("Zezima")
    finally:
        await client.aclose()

    assert r1 == r2
    assert call_count == 1  # only one HTTP request made


@pytest.mark.asyncio
async def test_different_usernames_are_cached_separately() -> None:
    call_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"user": request.url.path})

    client = make_client(httpx.MockTransport(respond))
    try:
        await client.get_summary("Zezima")
        await client.get_summary("Lynx Titan")
    finally:
        await client.aclose()

    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl() -> None:
    call_count = 0
    fake_time = [1000.0]

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"v": call_count})

    client = RuneProfileClient(
        base_url="https://api.runeprofile.com/v1",
        cache_ttl=60.0,
    )
    client._client = httpx.AsyncClient(
        base_url="https://api.runeprofile.com/v1",
        transport=httpx.MockTransport(respond),
    )

    try:
        with patch("app.services.runeprofile.time.monotonic", side_effect=lambda: fake_time[0]):
            r1 = await client.get_summary("Zezima")

        # Advance past TTL
        fake_time[0] = 1061.0
        with patch("app.services.runeprofile.time.monotonic", side_effect=lambda: fake_time[0]):
            r2 = await client.get_summary("Zezima")
    finally:
        await client.aclose()

    assert r1 == {"v": 1}
    assert r2 == {"v": 2}
    assert call_count == 2


@pytest.mark.asyncio
async def test_errors_are_not_cached() -> None:
    call_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"found": True})

    client = make_client(httpx.MockTransport(respond))
    try:
        with pytest.raises(RuneProfileError):
            await client.get_summary("Zezima")
        result = await client.get_summary("Zezima")
    finally:
        await client.aclose()

    assert result == {"found": True}
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_model_caches() -> None:
    call_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"playerModelBase64": "abc123"})

    client = make_client(httpx.MockTransport(respond))
    try:
        r1 = await client.get_model("Zezima")
        r2 = await client.get_model("Zezima")
    finally:
        await client.aclose()

    assert r1 == r2
    assert call_count == 1
