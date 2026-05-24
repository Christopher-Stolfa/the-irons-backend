"""Async client for the RuneProfile public API.

Docs: https://api.runeprofile.com/v1/docs
Source: https://github.com/ReinhardtR/runeprofile

The upstream API is read-only, cached for ~1 minute server-side, and
rate-limited (30/min anonymous, 120/min with an API key). All endpoints
work without an API key; supplying ``X-API-Key`` just raises the limit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from app.config import Settings

logger = logging.getLogger(__name__)


class RuneProfileError(HTTPException):
    """Raised when the upstream RuneProfile API returns a non-success status.

    Subclasses :class:`fastapi.HTTPException` so it surfaces directly to the
    client with an appropriate status code.
    """


class RuneProfileClient:
    """Thin async wrapper around the RuneProfile public API.

    One instance per process is intended; the underlying ``httpx.AsyncClient``
    holds a connection pool and should be closed on shutdown via :meth:`aclose`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        user_agent: str = "the-irons-backend",
        timeout: float = 10.0,
    ) -> None:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        if api_key:
            headers["X-API-Key"] = api_key

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> RuneProfileClient:
        return cls(
            base_url=settings.runeprofile_base_url,
            api_key=settings.runeprofile_api_key,
            user_agent=settings.runeprofile_user_agent,
            timeout=settings.runeprofile_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_summary(self, username: str) -> dict[str, Any]:
        """High-level overview across all tracked categories."""
        return await self._get(self._account_path(username))

    async def get_full_profile(self, username: str) -> dict[str, Any]:
        """Skills, quests, collection log, diaries, and combat achievements.

        This is the heavy "everything" endpoint; prefer the granular ones
        when you don't need it all at once.
        """
        return await self._get(f"{self._account_path(username)}/full")

    async def get_skills(self, username: str) -> dict[str, Any]:
        return await self._get(f"{self._account_path(username)}/skills")

    async def get_quests(self, username: str) -> dict[str, Any]:
        return await self._get(f"{self._account_path(username)}/quests")

    async def get_achievement_diaries(self, username: str) -> dict[str, Any]:
        return await self._get(f"{self._account_path(username)}/achievement-diaries")

    async def get_combat_achievements(self, username: str) -> dict[str, Any]:
        return await self._get(f"{self._account_path(username)}/combat-achievements")

    async def get_collection_log(self, username: str) -> dict[str, Any]:
        return await self._get(f"{self._account_path(username)}/collection-log")

    async def get_collection_log_tab(self, username: str, tab: str) -> dict[str, Any]:
        return await self._get(
            f"{self._account_path(username)}/collection-log/{quote(tab, safe='')}"
        )

    async def get_collection_log_page(self, username: str, tab: str, page: str) -> dict[str, Any]:
        return await self._get(
            f"{self._account_path(username)}/collection-log"
            f"/{quote(tab, safe='')}/{quote(page, safe='')}"
        )

    async def get_clan(
        self,
        name: str,
        *,
        cursor: str | None = None,
        direction: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Paginated clan member list.

        Upstream: ``GET /v1/clans/{name}``
        """
        params: dict[str, str | int] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if direction is not None:
            params["direction"] = direction
        if limit is not None:
            params["limit"] = limit
        return await self._get(
            f"/clans/{quote(name, safe='')}",
            params=params or None,
        )

    async def get_clan_members_with_models(
        self,
        name: str,
        *,
        pet: bool = True,
    ) -> dict[str, Any]:
        """Fetch clan roster and every member's 3D model in one call.

        1. Fetches the full clan member list (paginating if needed).
        2. Concurrently fetches each member's model.
        3. Returns a combined payload ready for the frontend.
        """
        all_members: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            page = await self.get_clan(name, cursor=cursor, limit=100)
            all_members.extend(page.get("members", []))
            if not page.get("hasMore"):
                break
            cursor = page.get("nextCursor")
            if not cursor:
                break

        semaphore = asyncio.Semaphore(10)

        async def fetch_member_model(member: dict[str, Any]) -> dict[str, Any]:
            username = member["username"]
            async with semaphore:
                try:
                    model_data = await self.get_model(username, pet=pet)
                    model_base64 = model_data.get("playerModelBase64")
                except Exception:
                    logger.warning("Failed to fetch model for %s", username)
                    model_base64 = None

            return {
                "username": username,
                "accountType": member.get("accountType"),
                "clan": member.get("clan"),
                "playerModelBase64": model_base64,
            }

        results = await asyncio.gather(
            *(fetch_member_model(m) for m in all_members)
        )

        return {
            "clanName": name,
            "total": len(results),
            "members": list(results),
        }

    async def get_model(
        self,
        username: str,
        *,
        pet: bool = True,
    ) -> dict[str, Any]:
        """Player 3D model as base64-encoded binary PLY.

        This hits the undocumented ``/profiles/models/{username}`` endpoint
        which lives outside the ``/v1`` namespace, so we construct the full
        URL rather than going through :meth:`_get` (which would prepend ``/v1``).
        """
        origin = str(self._client.base_url).split("/v1")[0].rstrip("/")
        url = f"{origin}/profiles/models/{quote(username, safe='')}"
        params: dict[str, str] = {}
        if pet:
            params["pet"] = "true"

        try:
            response = await self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RuneProfileError(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="RuneProfile API timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise RuneProfileError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reach RuneProfile API",
            ) from exc

        if response.is_success:
            return response.json()
        if response.status_code == 404:
            raise RuneProfileError(
                status_code=404,
                detail=f"No RuneProfile model found for '{username}'",
            )
        if response.status_code == 429:
            raise RuneProfileError(
                status_code=429,
                detail="RuneProfile rate limit exceeded",
            )
        raise RuneProfileError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected RuneProfile API response: {response.status_code}",
        )

    async def get_activities(
        self,
        username: str,
        *,
        cursor: str | None = None,
        direction: str | None = None,
        limit: int | None = None,
        activity_types: str | None = None,
    ) -> dict[str, Any]:
        """Paginated activity feed.

        ``activity_types`` is forwarded as the upstream's ``activityTypes``
        query param (comma-separated list, e.g. ``"xp_milestone,quest_completed"``).
        """
        params: dict[str, str | int] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if direction is not None:
            params["direction"] = direction
        if limit is not None:
            params["limit"] = limit
        if activity_types is not None:
            params["activityTypes"] = activity_types
        return await self._get(
            f"{self._account_path(username)}/activities",
            params=params or None,
        )

    @staticmethod
    def _account_path(username: str) -> str:
        return f"/accounts/{quote(username, safe='')}"

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise RuneProfileError(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="RuneProfile API timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise RuneProfileError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to reach RuneProfile API",
            ) from exc

        if response.is_success:
            return response.json()

        # Forward common upstream statuses with a friendly detail.
        if response.status_code == status.HTTP_404_NOT_FOUND:
            raise RuneProfileError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="RuneProfile account not found",
            )
        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise RuneProfileError(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="RuneProfile rate limit exceeded",
            )

        raise RuneProfileError(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected RuneProfile API response: {response.status_code}",
        )
