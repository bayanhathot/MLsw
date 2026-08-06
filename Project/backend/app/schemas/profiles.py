"""
profiles.py

Pydantic schemas for profile customization and listening stats.
"""

from pydantic import BaseModel, ConfigDict, Field


class ProfileRead(BaseModel):
    """
    Response shape for GET/PATCH /users/me/profile.
    """

    model_config = ConfigDict(from_attributes=True)

    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    favorite_genres: list[str] | None = None
    theme_preference: str


class ProfileUpdate(BaseModel):
    """
    Request body for PATCH /users/me/profile.

    Every field is optional - only fields actually present in the
    request are applied (see profile_service.update_profile, which
    reads this via model_dump(exclude_unset=True)), so omitting a
    field leaves it unchanged rather than clearing it.
    """

    display_name: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=1000)
    bio: str | None = Field(default=None, max_length=280)
    favorite_genres: list[str] | None = None
    theme_preference: str | None = Field(default=None, pattern="^(dark|light|system)$")


class FavoriteArtist(BaseModel):
    """
    One entry in the favorite_artists ranking.
    """

    artist: str
    seconds_listened: int


class ProfileStatsRead(BaseModel):
    """
    Response shape for GET /users/{username}/stats.

    Computed on demand from play_events - not stored/denormalized.
    """

    minutes_listened: int
    favorite_artists: list[FavoriteArtist]
