"""Async client for the RuneProfile public API.

Docs: https://api.runeprofile.com/v1/docs
Source: https://github.com/ReinhardtR/runeprofile

The upstream API is read-only, cached for ~1 minute server-side, and
rate-limited (30/min anonymous, 120/min with an API key). All endpoints
work without an API key; supplying ``X-API-Key`` just raises the limit.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from app.config import Settings


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
