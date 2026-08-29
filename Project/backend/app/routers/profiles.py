"""Private profile settings, Music Identity, and music-first public profiles."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.core.rate_limit import write_rate_limit
from app.database.database import get_db
from app.database.models.mix import Mix
from app.database.models.music_identity import UserMusicProfile
from app.database.models.profile import Profile
from app.database.models.session import UserPreference
from app.database.models.user import User
from app.database.models.social import UserBlock
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import (
    MixFeedItem,
    MixRead,
    MusicIdentityPrivacyUpdate,
    MusicIdentityRead,
    PreferenceRead,
    ProfileRead,
    ProfileStatsRead,
    ProfileUpdate,
    PromptShortcutRead,
    PublicMusicIdentityRead,
    PublicProfileRead,
)
from app.services import (
    mix_service,
    music_identity_service,
    profile_service,
    prompt_shortcuts,
    social_service,
)
from app.services.auth_service import get_user_by_username

router = APIRouter(prefix="/users", tags=["profiles"])


def _user_or_404(db: Session, username: str) -> User:
    user = get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("/me/profile", response_model=ProfileRead)
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return profile_service.get_or_create(db, current_user.id)


@router.patch("/me/profile", response_model=ProfileRead)
def update_profile(
    request: ProfileUpdate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = profile_service.get_or_create(db, current_user.id)
    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/me/preferences", response_model=list[PreferenceRead])
def get_preferences(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(UserPreference)
        .filter(UserPreference.user_id == current_user.id)
        .order_by(UserPreference.score.desc(), UserPreference.count.desc())
        .all()
    )


@router.get("/me/prompt-shortcuts", response_model=list[PromptShortcutRead])
def get_prompt_shortcuts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A logged-in user's own repeated-intent prompt shortcuts (see
    services/prompt_shortcuts.py), ranked by frequency then recency. Guests
    have no identity to key off, so PromptComposer.svelte only calls this
    for an authenticated user and falls back to the static PRESETS list
    entirely otherwise."""

    return prompt_shortcuts.top_shortcuts(db, current_user.id)


@router.get("/me/music-identity", response_model=MusicIdentityRead)
def my_music_identity(
    period: str = Query(default="all", pattern="^(7d|30d|6m|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return music_identity_service.build_music_identity(db, current_user.id, period)


@router.patch("/me/music-identity/privacy", response_model=MusicIdentityRead)
def set_music_identity_privacy(
    request: MusicIdentityPrivacyUpdate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = music_identity_service.get_or_create_music_profile(db, current_user.id)
    visibility = request.visibility
    if visibility is None and request.is_public is not None:
        visibility = "public" if request.is_public else "private"
    if visibility is None:
        raise HTTPException(status_code=422, detail="Choose a Music Identity visibility.")
    music_identity_service.set_visibility(profile, visibility)
    db.commit()
    db.refresh(profile)
    return music_identity_service.build_music_identity(db, current_user.id, "all")


@router.get("/{username}/profile", response_model=PublicProfileRead)
def public_profile(
    username: str,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, username)
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    music_profile = db.query(UserMusicProfile).filter(UserMusicProfile.user_id == user.id).first()
    viewer_id = current_user.id if current_user else None
    if viewer_id is not None and social_service.has_block(db, user.id, viewer_id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    visibility = music_profile.visibility if music_profile else "private"
    return {
        "id": user.id,
        "username": user.username,
        "display_name": profile.display_name if profile else None,
        "avatar_url": profile.avatar_url if profile else None,
        "bio": profile.bio if profile else None,
        "favorite_genres": profile.favorite_genres if profile else None,
        "member_since": user.created_at,
        "stats": profile_service.engagement_stats(db, user.id, viewer_id),
        "music_identity_public": visibility == "public",
        "music_identity_visibility": visibility,
        "friend_count": len(social_service.friend_ids(db, user.id)),
        "mutual_friend_count": len(social_service.friend_ids(db, user.id) & social_service.friend_ids(db, viewer_id)) if viewer_id and viewer_id != user.id else 0,
        "published_mix_count": db.query(Mix).filter_by(owner_id=user.id, status="published").count(),
        "relationship_status": social_service.relationship_status(db, viewer_id, user.id),
        "viewer_has_blocked": bool(viewer_id and db.query(UserBlock).filter_by(blocker_id=viewer_id, blocked_id=user.id).first()),
    }


@router.get("/{username}/music-identity", response_model=PublicMusicIdentityRead)
def public_music_identity(
    username: str,
    period: str = Query(default="all", pattern="^(7d|30d|6m|all)$"),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, username)
    profile = db.query(UserMusicProfile).filter(UserMusicProfile.user_id == user.id).first()
    if profile is None:
        return {"username": user.username, "is_public": False, "music_identity": None}
    viewer_id = current_user.id if current_user else None
    if viewer_id is not None and social_service.has_block(db, user.id, viewer_id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    allowed = profile.visibility == "public" or (
        profile.visibility == "friends" and viewer_id is not None and social_service.are_friends(db, viewer_id, user.id)
    ) or viewer_id == user.id
    if not allowed:
        return {"username": user.username, "is_public": False, "music_identity": None}
    identity = music_identity_service.build_music_identity(db, user.id, period)
    return {"username": user.username, "is_public": True, "music_identity": identity}


@router.get("/{username}/mixes", response_model=list[MixFeedItem])
def public_user_mixes(
    username: str,
    limit: int = Query(default=12, ge=1, le=50),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, username)
    viewer_id = current_user.id if current_user else None
    if viewer_id is not None and social_service.has_block(db, user.id, viewer_id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    mixes = (
        db.query(Mix)
        .options(selectinload(Mix.owner), selectinload(Mix.segments))
        .filter(Mix.owner_id == user.id, Mix.status == "published")
        .order_by(Mix.published_at.desc(), Mix.id.desc())
        .limit(limit)
        .all()
    )
    return [
        MixFeedItem(
            **MixRead.model_validate(mix).model_dump(),
            owner=mix.owner,
            like_count=mix_service.like_count(db, mix.id),
            is_liked=mix_service.liked_by(db, mix.id, viewer_id),
            is_saved=mix_service.saved_by(db, mix.id, viewer_id),
        )
        for mix in mixes
    ]


@router.get("/{username}/stats", response_model=ProfileStatsRead)
def profile_stats(
    username: str,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    user = _user_or_404(db, username)
    viewer_id = current_user.id if current_user else None
    if viewer_id is not None and social_service.has_block(db, user.id, viewer_id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    return profile_service.engagement_stats(db, user.id, viewer_id)
