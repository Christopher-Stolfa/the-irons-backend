from typing import Any

import httpx
import pytest

from app.services.runeprofile import RuneProfileClient, RuneProfileError


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
