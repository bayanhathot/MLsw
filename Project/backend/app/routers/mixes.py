"""
Mixes router for Zonix.

This router exposes API endpoints related to generating AI DJ mixes.

Current endpoint:
POST /mixes/start

Main idea:
The user does not receive one song.
Instead, the backend creates a mix queue made of multiple song segments.

Current MVP flow:
1. Frontend sends a prompt to POST /mixes/start.
2. Authentication identifies the user creating the mix.
3. Backend searches Audius for relevant tracks.
4. Backend stores a private draft mix in PostgreSQL.
5. Each returned track is stored as a simple 45-second segment.
6. Backend returns the saved mix and its ordered segment queue.

Important:
This router creates a "mix plan", not a real audio file.
Real audio cutting, beat detection, and crossfading are future work.

Future improvements:
- Generate smarter segments instead of always using 0-45 seconds.
- Use feedback buttons to choose the next segment.
- Add real crossfade/playback logic on the frontend.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models.mix import Mix
from app.database.models.mix_like import MixLike
from app.database.models.mix_segment import MixSegment as MixSegmentModel
from app.database.models.saved_mix import SavedMix
from app.database.models.user import User
from app.database.models.user_follow import UserFollow
from app.routers.auth import get_current_user
from app.schemas import MixRead, MixUpdate
from app.schemas import MixFeedItem
from app.services.audius_service import search_tracks

router = APIRouter(prefix="/mixes", tags=["mixes"])


class StartMixRequest(BaseModel):
    """
      Request body for creating a new mix.

      Example:
      {
          "prompt": "chill electronic focus"
      }

      The prompt describes the vibe the user wants.
      """
    prompt: str = Field(..., min_length=1, max_length=300)


class MixSegment(BaseModel):
    """
    Represents one segment in the generated mix queue.

    In the MVP, every segment is created from one Audius track.
    Later, a segment should represent the best part of a song,
    such as the chorus, drop, vocal part, or emotional section.
    """
    position: int
    title: str
    artist: str
    audio_url: str
    cover_url: str | None = None
    start_second: int
    end_second: int
    transition_to_next: str
    source: str
    source_track_id: str


class StartMixResponse(BaseModel):
    """
    Response returned by POST /mixes/start.

    Fields:
        session_id:
            Unique id for this generated mix.

        prompt:
            The original prompt sent by the user.

        segments:
            Ordered list of segments that the frontend should play.
    """
    session_id: str
    prompt: str
    segments: list[MixSegment]


@router.post("/start", response_model=MixRead)
def start_mix(
    request: StartMixRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a mix plan and save it as a private draft.

    FastAPI validates the incoming prompt with ``StartMixRequest``. The
    ``get_current_user`` dependency requires a valid login and identifies the
    owner, while ``get_db`` supplies the PostgreSQL session used by this
    request.

    The endpoint searches Audius for five matching tracks, creates one
    ``mixes`` row, and creates an ordered ``mix_segments`` row for every
    returned track. The database transaction is committed only after the mix
    and all of its segments have been prepared.

    The result remains a mix plan: each segment references source audio and a
    time range. This endpoint does not cut or combine audio files.

    Raises:
        HTTPException: 401 when no valid user is logged in (from the auth
            dependency), or 404 when Audius returns no matching tracks.

    Returns:
        Mix: The saved draft mix, serialized according to ``MixRead``.
    """
    # Search first so an unsuccessful search does not create an empty draft.
    tracks = search_tracks(request.prompt, limit=5)

    if not tracks:
        raise HTTPException(
            status_code=404,
            detail="No tracks found for this prompt.",
        )

    # The prompt is also the automatic title because this MVP has no edit flow.
    mix = Mix(
        owner_id=current_user.id,
        title=request.prompt[:120],
        prompt=request.prompt,
        status="draft",
    )

    db.add(mix)

    # Flush the pending INSERT to obtain mix.id before creating child rows.
    # The transaction is not permanent until db.commit() below.
    db.flush()

    # Store one ordered 0-45 second segment for each Audius search result.
    for index, track in enumerate(tracks):
        duration = track.get("duration") or 60

        segment = MixSegmentModel(
            mix_id=mix.id,
            position=index + 1,
            title=track["title"],
            artist=track["artist"],
            audio_url=track["audio_url"],
            cover_url=track.get("cover_url"),
            start_second=0,
            end_second=min(45, duration),
            transition_to_next="crossfade",
            source=track["source"],
            source_track_id=track["source_track_id"],
        )

        db.add(segment)

    # Commit the parent mix and every segment as one database transaction.
    db.commit()

    # Reload database-generated/default values before FastAPI serializes it.
    db.refresh(mix)

    return mix

@router.get("/mine", response_model=list[MixRead])
def get_my_mixes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all mixes created by the logged-in user.

    Draft and published mixes are included, ordered from newest to oldest.
    Authentication is required.
    """
    return (
        db.query(Mix)
        .filter(Mix.owner_id == current_user.id)
        .order_by(Mix.created_at.desc())
        .all()
    )





@router.get("/saved", response_model=list[MixRead])
def get_saved_mixes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return published mixes bookmarked by the logged-in user.

    A saved mix is a private bookmark rather than a public reaction. This
    endpoint joins ``saved_mixes`` to ``mixes`` so it can return the complete
    mix records saved by the current user.

    Drafts are excluded because only published mixes may be saved. Results are
    ordered by bookmark creation time, with the most recently saved mix first.

    Args:
        db: Database session supplied by FastAPI.
        current_user: Logged-in user supplied by the authentication dependency.

    Returns:
        The user's saved published mixes, serialized according to ``MixRead``.
    """
    return (
        db.query(Mix)
        # Connect each bookmark to the complete mix that it references.
        .join(SavedMix, SavedMix.mix_id == Mix.id)
        # Restrict the private library to the current logged-in user.
        .filter(
            SavedMix.user_id == current_user.id,
            Mix.status == "published",
        )
        # Show the most recently saved mixes first.
        .order_by(SavedMix.created_at.desc())
        .all()
    )


@router.patch("/{mix_id}", response_model=MixRead)
def update_mix(
    mix_id: int,
    request: MixUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the public information of a mix.

    Only the user who owns the mix may update it. This endpoint changes
    metadata such as the title, description, and cover image. It does not
    change the songs, segment order, timing, or transitions.

    Args:
        mix_id: Database ID of the mix being updated.
        request: New title, description, and cover URL.
        db: Database session supplied by FastAPI.
        current_user: Logged-in user supplied by the authentication dependency.

    Raises:
        HTTPException: 404 if the mix does not exist.
        HTTPException: 403 if the logged-in user does not own the mix.

    Returns:
        The updated mix, serialized using ``MixRead``.
    """
    mix = db.query(Mix).filter(Mix.id == mix_id).first()

    if mix is None:
        raise HTTPException(
            status_code=404,
            detail="Mix not found.",
        )


    if mix.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You do not own this mix.",
        )

    mix.title = request.title
    mix.description = request.description
    mix.cover_url = request.cover_url

    db.commit()
    db.refresh(mix)

    return mix

@router.post("/{mix_id}/publish", response_model=MixRead)
def publish_mix(
    mix_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Publish a mix owned by the logged-in user.

    A newly generated mix starts with the ``draft`` status. This endpoint
    changes its status to ``published`` so that it can appear in the public
    community feed.

    Publishing does not change the mix title, prompt, cover, or segments.
    Only the owner of the mix is allowed to publish it.

    Calling this endpoint for an already-published mix is safe. The endpoint
    returns the existing mix without changing its original publication time.

    Args:
        mix_id: Database ID of the mix that should be published.
        db: Database session supplied by FastAPI.
        current_user: Logged-in user supplied by the authentication dependency.

    Raises:
        HTTPException: 404 if the requested mix does not exist.
        HTTPException: 403 if the logged-in user does not own the mix.

    Returns:
        The published mix, serialized according to ``MixRead``.
    """
    # Find the mix using its permanent PostgreSQL ID.
    mix = db.query(Mix).filter(Mix.id == mix_id).first()

    if mix is None:
        raise HTTPException(
            status_code=404,
            detail="Mix not found.",
        )

    # A user must never be able to publish another user's mix.
    if mix.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You do not own this mix.",
        )

    # Keep this endpoint idempotent. Repeated requests do not reset the
    # original publication time.
    if mix.status == "published":
        return mix

    # Make the mix publicly visible and record when it was published.
    mix.status = "published"
    mix.published_at = datetime.utcnow()

    db.commit()
    db.refresh(mix)

    return mix



@router.get("/feed", response_model=list[MixFeedItem])
def get_feed(
    scope: Literal["discover", "following", "friends"] = Query(default="discover"),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return published mixes with social information.

    Every feed item includes the owner, total number of likes, and whether the
    logged-in user has liked or saved that mix.

    Authentication is required in the current MVP so the backend can calculate
    the current user's social state.
    """
    mix_query = db.query(Mix).filter(Mix.status == "published")

    if scope == "following":
        followed_user_ids = (
            db.query(UserFollow.following_id)
            .filter(UserFollow.follower_id == current_user.id)
            .scalar_subquery()
        )
        mix_query = mix_query.filter(
            (Mix.owner_id.in_(followed_user_ids))
            | (Mix.owner_id == current_user.id)
        )
    elif scope == "friends":
        followed_user_ids = (
            db.query(UserFollow.following_id)
            .filter(UserFollow.follower_id == current_user.id)
            .scalar_subquery()
        )
        follower_user_ids = (
            db.query(UserFollow.follower_id)
            .filter(UserFollow.following_id == current_user.id)
            .scalar_subquery()
        )
        mix_query = mix_query.filter(
            Mix.owner_id.in_(followed_user_ids),
            Mix.owner_id.in_(follower_user_ids),
        )

    mixes = (
        mix_query.order_by(Mix.published_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    feed_items = []

    for mix in mixes:
        # Count every like belonging to this mix.
        like_count = (
            db.query(MixLike)
            .filter(MixLike.mix_id == mix.id)
            .count()
        )

        # Check whether the logged-in user liked this mix.
        is_liked = (
            db.query(MixLike)
            .filter(
                MixLike.mix_id == mix.id,
                MixLike.user_id == current_user.id,
            )
            .first()
            is not None
        )

        # Check whether the logged-in user saved this mix.
        is_saved = (
            db.query(SavedMix)
            .filter(
                SavedMix.mix_id == mix.id,
                SavedMix.user_id == current_user.id,
            )
            .first()
            is not None
        )

        is_own = mix.owner_id == current_user.id
        is_following = False
        follows_you = False

        if not is_own:
            is_following = (
                db.query(UserFollow)
                .filter(
                    UserFollow.follower_id == current_user.id,
                    UserFollow.following_id == mix.owner_id,
                )
                .first()
                is not None
            )
            follows_you = (
                db.query(UserFollow)
                .filter(
                    UserFollow.follower_id == mix.owner_id,
                    UserFollow.following_id == current_user.id,
                )
                .first()
                is not None
            )

        is_friend = is_following and follows_you

        feed_items.append(
            {
                "id": mix.id,
                "title": mix.title,
                "prompt": mix.prompt,
                "description": mix.description,
                "cover_url": mix.cover_url,
                "owner": {
                    "id": mix.owner.id,
                    "username": mix.owner.username,
                },
                "like_count": like_count,
                "is_liked": is_liked,
                "is_saved": is_saved,
                "is_following": is_following,
                "follows_you": follows_you,
                "is_friend": is_friend,
                "is_own": is_own,
                "published_at": mix.published_at,
                "segments": mix.segments,
            }
        )

    return feed_items
@router.put("/{mix_id}/like")
def like_mix(
    mix_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Like a published mix as the logged-in user.

    A like is represented by one row in ``mix_likes`` connecting the current
    user to the selected mix. Drafts cannot be liked because they are not
    public. The table's unique constraint prevents the same user from liking
    the same mix more than once.

    This endpoint uses PUT because the operation is idempotent: calling it
    repeatedly leaves the mix liked and does not create duplicate rows.

    Args:
        mix_id: Database ID of the published mix to like.
        db: Database session supplied by FastAPI.
        current_user: Logged-in user supplied by the authentication dependency.

    Raises:
        HTTPException: 404 if the mix does not exist or is not published.

    Returns:
        The mix ID, the user's current liked state, and the total like count.
    """
    # Only public, published mixes can receive likes.
    mix = (
        db.query(Mix)
        .filter(
            Mix.id == mix_id,
            Mix.status == "published",
        )
        .first()
    )

    if mix is None:
        raise HTTPException(
            status_code=404,
            detail="Published mix not found.",
        )

    # Check for an existing row before inserting so repeated requests are safe.
    existing_like = (
        db.query(MixLike)
        .filter(
            MixLike.mix_id == mix_id,
            MixLike.user_id == current_user.id,
        )
        .first()
    )

    if existing_like is None:
        db.add(
            MixLike(
                mix_id=mix_id,
                user_id=current_user.id,
            )
        )
        db.commit()

    # Count all users who currently like this mix for the frontend display.
    like_count = (
        db.query(MixLike)
        .filter(MixLike.mix_id == mix_id)
        .count()
    )

    return {
        "mix_id": mix_id,
        "is_liked": True,
        "like_count": like_count,
    }
@router.delete("/{mix_id}/like")
def unlike_mix(
    mix_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the logged-in user's like from a mix.

    This is an "unlike" operation, not a negative dislike or downvote. It
    deletes only the ``mix_likes`` row belonging to the current user. If no
    such row exists, the endpoint still succeeds and returns an unliked state.

    This endpoint is idempotent: repeated DELETE requests have the same final
    result and never affect likes belonging to other users.

    Args:
        mix_id: Database ID of the mix to unlike.
        db: Database session supplied by FastAPI.
        current_user: Logged-in user supplied by the authentication dependency.

    Returns:
        The mix ID, the user's current liked state, and the total like count.
    """
    # Find only this user's like; never delete another user's reaction.
    like = (
        db.query(MixLike)
        .filter(
            MixLike.mix_id == mix_id,
            MixLike.user_id == current_user.id,
        )
        .first()
    )

    # Deleting a missing like is treated as success because the desired final
    # state (not liked) has already been reached.
    if like is not None:
        db.delete(like)
        db.commit()

    # Return the updated total so the UI can refresh its displayed count.
    like_count = (
        db.query(MixLike)
        .filter(MixLike.mix_id == mix_id)
        .count()
    )

    return {
        "mix_id": mix_id,
        "is_liked": False,
        "like_count": like_count,
    }
@router.put("/{mix_id}/save")
def save_mix(
    mix_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mix = (
        db.query(Mix)
        .filter(
            Mix.id == mix_id,
            Mix.status == "published",
        )
        .first()
    )

    if mix is None:
        raise HTTPException(
            status_code=404,
            detail="Published mix not found.",
        )

    existing_save = (
        db.query(SavedMix)
        .filter(
            SavedMix.mix_id == mix_id,
            SavedMix.user_id == current_user.id,
        )
        .first()
    )

    if existing_save is None:
        db.add(
            SavedMix(
                mix_id=mix_id,
                user_id=current_user.id,
            )
        )
        db.commit()

    return {
        "mix_id": mix_id,
        "is_saved": True,
    }

@router.delete("/{mix_id}/save")
def unsave_mix(
    mix_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    saved_mix = (
        db.query(SavedMix)
        .filter(
            SavedMix.mix_id == mix_id,
            SavedMix.user_id == current_user.id,
        )
        .first()
    )

    if saved_mix is not None:
        db.delete(saved_mix)
        db.commit()

    return {
        "mix_id": mix_id,
        "is_saved": False,
    }
