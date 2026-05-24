from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.config import Settings, get_settings
from app.services.runeprofile import RuneProfileClient

router = APIRouter(prefix="/runeprofile", tags=["runeprofile"])

UsernamePath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=12,
        pattern=r"^[A-Za-z0-9 _\-]+$",
        description="Old School RuneScape display name (1-12 chars).",
        examples=["Zezima"],
    ),
]

CollectionLogTabPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        description="Collection log tab name (e.g. Bosses, Raids, Clues, Minigames, Other). Case-insensitive.",
        examples=["Bosses"],
    ),
]

CollectionLogPagePath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=128,
        description="Collection log page name within a tab (e.g. Abyssal Sire, Barrows Chests). Case-insensitive.",
        examples=["Abyssal Sire"],
    ),
]


def get_runeprofile_client(request: Request) -> RuneProfileClient:
    """FastAPI dependency that returns the app-scoped RuneProfile client.

    Tests can override this via ``app.dependency_overrides`` to inject a fake.
    """
    return request.app.state.runeprofile_client


ClanNamePath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=100,
        description="Clan name (e.g. The Irons).",
        examples=["The Irons"],
    ),
]


@router.get(
    "/clan/{name}",
    summary="Clan members",
    response_model=dict[str, Any],
    description=(
        "Returns clan details and a paginated member list from RuneProfile. "
        "Each member includes username, account type, and clan rank."
    ),
)
async def get_clan(
    name: ClanNamePath,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous response."),
    ] = None,
    direction: Annotated[
        Literal["next", "prev"] | None,
        Query(description="Pagination direction. Defaults to next."),
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=100, description="Members per page (1-100, default 50)."),
    ] = None,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_clan(name, cursor=cursor, direction=direction, limit=limit)


@router.get(
    "/clan/{name}/members-with-models",
    summary="Clan members with 3D models",
    response_model=dict[str, Any],
    description=(
        "Fetches the full clan roster from RuneProfile, then batch-fetches "
        "every member's 3D model server-side. Returns a single payload with "
        "each member's username, account type, clan rank, and base64-encoded "
        "PLY model data. Members whose model could not be fetched will have "
        "`playerModelBase64: null`."
    ),
)
async def get_clan_members_with_models(
    name: ClanNamePath,
    pet: Annotated[
        bool,
        Query(description="Include pets in the models."),
    ] = True,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_clan_members_with_models(name, pet=pet)


@router.get(
    "/me",
    summary="My RuneProfile (full profile)",
    response_model=dict[str, Any],
    description=(
        "Returns the full profile for the username configured via "
        "`RUNEPROFILE_USERNAME`. Convenience endpoint for the local frontend."
    ),
)
async def get_me(
    settings: Settings = Depends(get_settings),
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    if not settings.runeprofile_username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RUNEPROFILE_USERNAME is not configured",
        )
    return await client.get_full_profile(settings.runeprofile_username)


@router.get(
    "/{username}",
    summary="RuneProfile summary for an account",
    response_model=dict[str, Any],
)
async def get_summary(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_summary(username)


@router.get(
    "/{username}/model",
    summary="Player 3D model (PLY)",
    response_model=dict[str, Any],
    description=(
        "Proxies the undocumented RuneProfile player model endpoint. "
        "Returns `{ playerModelBase64: string }` where the base64-decoded "
        "payload is a binary PLY file with vertex-colored geometry."
    ),
)
async def get_model(
    username: UsernamePath,
    pet: Annotated[
        bool,
        Query(description="Include the player's pet in the model."),
    ] = True,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_model(username, pet=pet)


@router.get(
    "/{username}/full",
    summary="Full RuneProfile for an account",
    response_model=dict[str, Any],
    description=(
        "Skills, quests, collection log, achievement diaries, and combat "
        "achievements in a single response. Heavy endpoint — prefer the "
        "granular endpoints unless you really need everything."
    ),
)
async def get_full(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_full_profile(username)


@router.get(
    "/{username}/skills",
    summary="Skills",
    response_model=dict[str, Any],
    description="Skill levels and experience for the account.",
)
async def get_skills(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_skills(username)


@router.get(
    "/{username}/quests",
    summary="Quests",
    response_model=dict[str, Any],
    description="Quest completion status for the account.",
)
async def get_quests(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_quests(username)


@router.get(
    "/{username}/achievement-diaries",
    summary="Achievement diaries",
    response_model=dict[str, Any],
    description="Achievement diary completion progress per area and tier.",
)
async def get_achievement_diaries(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_achievement_diaries(username)


@router.get(
    "/{username}/combat-achievements",
    summary="Combat achievements",
    response_model=dict[str, Any],
    description="Combat achievement completion progress per tier.",
)
async def get_combat_achievements(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_combat_achievements(username)


@router.get(
    "/{username}/collection-log",
    summary="Collection log",
    response_model=dict[str, Any],
    description="Full collection log organized by tabs and pages.",
)
async def get_collection_log(
    username: UsernamePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_collection_log(username)


@router.get(
    "/{username}/collection-log/{tab}",
    summary="Collection log tab",
    response_model=dict[str, Any],
    description="A single collection log tab and its pages.",
)
async def get_collection_log_tab(
    username: UsernamePath,
    tab: CollectionLogTabPath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_collection_log_tab(username, tab)


@router.get(
    "/{username}/collection-log/{tab}/{page}",
    summary="Collection log page",
    response_model=dict[str, Any],
    description="A single collection log page and its items.",
)
async def get_collection_log_page(
    username: UsernamePath,
    tab: CollectionLogTabPath,
    page: CollectionLogPagePath,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_collection_log_page(username, tab, page)


@router.get(
    "/{username}/activities",
    summary="Activity feed",
    response_model=dict[str, Any],
    description=(
        "Paginated feed of recent account activities. Cursors are opaque "
        "strings returned by previous responses; pass them back as `cursor` "
        "with the appropriate `direction` to page through results."
    ),
)
async def get_activities(
    username: UsernamePath,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor from a previous response."),
    ] = None,
    direction: Annotated[
        Literal["next", "prev"] | None,
        Query(description="Pagination direction. Defaults to next."),
    ] = None,
    limit: Annotated[
        int | None,
        Query(ge=1, le=50, description="Items per page (1-50, default 20)."),
    ] = None,
    activity_types: Annotated[
        str | None,
        Query(
            alias="activityTypes",
            description=(
                "Comma-separated list of activity types to filter by "
                "(e.g. `xp_milestone,quest_completed`)."
            ),
        ),
    ] = None,
    client: RuneProfileClient = Depends(get_runeprofile_client),
) -> dict[str, Any]:
    return await client.get_activities(
        username,
        cursor=cursor,
        direction=direction,
        limit=limit,
        activity_types=activity_types,
    )
