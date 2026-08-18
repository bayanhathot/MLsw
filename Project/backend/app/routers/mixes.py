"""Generated mix API and its public feed/private library."""


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.core.rate_limit import write_rate_limit
from app.core.time import utc_now
from app.database.database import get_db
from app.database.models.mix import Mix
from app.database.models.mix_social import MixLike, SavedMix
from app.database.models.user import User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas import (
    MixFeedItem,
    MixLibraryRead,
    MixRead,
    NotificationRead,
    MixUpdate,
    StartMixRequest,
)
from app.services import forum_service, mix_service, social_service
from app.services.channel_hub import channel_hub
from app.services.pipeline.dependencies import (
    get_audio_renderer,
    get_audius_candidate_retriever,
    get_mix_candidate_retriever,
    get_segment_selector,
    get_transition_planner,
    get_vibe_understander,
)
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)

router = APIRouter(prefix="/mixes", tags=["mixes"])


def _get_or_404(db: Session, mix_id: int) -> Mix:
    mix = mix_service.get_mix(db, mix_id)
    if mix is None:
        raise HTTPException(status_code=404, detail="Mix not found.")
    return mix


def _feed_item(db: Session, mix: Mix, user_id: int | None) -> MixFeedItem:
    return MixFeedItem(
        **MixRead.model_validate(mix).model_dump(),
        owner=mix.owner,
        like_count=mix_service.like_count(db, mix.id),
        is_liked=mix_service.liked_by(db, mix.id, user_id),
        is_saved=mix_service.saved_by(db, mix.id, user_id),
    )


@router.post("/start", response_model=MixRead)
def start_mix(
    request: StartMixRequest,
    _: None = Depends(write_rate_limit),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
    vibe: VibeUnderstander = Depends(get_vibe_understander),
    retriever: CandidateRetriever = Depends(get_mix_candidate_retriever),
    fallback_retriever: CandidateRetriever = Depends(get_audius_candidate_retriever),
    selector: SegmentSelector = Depends(get_segment_selector),
    planner: TransitionPlanner = Depends(get_transition_planner),
    renderer: AudioRenderer = Depends(get_audio_renderer),
):
    """Create a persisted mix; a weak/empty catalog match falls back to Audius."""

    return mix_service.create_mix(
        db,
        request.prompt,
        current_user.id if current_user else None,
        vibe=vibe,
        retriever=retriever,
        fallback_retriever=fallback_retriever,
        selector=selector,
        planner=planner,
        renderer=renderer,
    )


@router.get("/feed", response_model=list[MixFeedItem])
def get_feed(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Mix)
        .options(selectinload(Mix.owner), selectinload(Mix.segments))
        .filter(Mix.status == "published", Mix.owner_id.is_not(None))
    )
    if current_user is not None:
        blocked_ids = social_service.blocked_user_ids(db, current_user.id)
        if blocked_ids:
            query = query.filter(~Mix.owner_id.in_(blocked_ids))
    mixes = (
        query
        .order_by(Mix.published_at.desc(), Mix.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_feed_item(db, mix, current_user.id if current_user else None) for mix in mixes]


def _owned_mixes(db: Session, user_id: int) -> list[Mix]:
    return (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .filter(Mix.owner_id == user_id)
        .order_by(Mix.created_at.desc())
        .all()
    )


def _saved_mixes(db: Session, user_id: int) -> list[Mix]:
    return (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .join(SavedMix, SavedMix.mix_id == Mix.id)
        .filter(SavedMix.user_id == user_id, Mix.status == "published")
        .order_by(SavedMix.created_at.desc())
        .all()
    )


@router.get("/library", response_model=MixLibraryRead)
def get_library(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return {"owned": _owned_mixes(db, current_user.id), "saved": _saved_mixes(db, current_user.id)}


@router.get("/mine", response_model=list[MixRead])
def get_owned(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _owned_mixes(db, current_user.id)


@router.get("/saved", response_model=list[MixRead])
def get_saved(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _saved_mixes(db, current_user.id)


@router.get("/{mix_id}", response_model=MixRead)
def read_mix(
    mix_id: int,
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    mix = _get_or_404(db, mix_id)
    if mix.status != "published":
        raise HTTPException(status_code=404, detail="Published mix not found.")
    if (
        current_user is not None
        and mix.owner_id is not None
        and social_service.is_blocked_between(db, current_user.id, mix.owner_id)
    ):
        raise HTTPException(status_code=404, detail="Published mix not found.")
    return mix


@router.patch("/{mix_id}", response_model=MixRead)
def update_mix(
    mix_id: int,
    request: MixUpdate,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = _get_or_404(db, mix_id)
    if mix.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this mix.")
    mix.title = request.title
    mix.description = request.description
    mix.cover_url = request.cover_url
    db.commit()
    db.refresh(mix)
    return mix


@router.post("/{mix_id}/publish", response_model=MixRead)
def publish_mix(
    mix_id: int,
    _: None = Depends(write_rate_limit),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mix = _get_or_404(db, mix_id)
    if mix.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this mix.")
    if mix.status != "published":
        mix.status = "published"
        mix.published_at = utc_now()
        db.commit()
        db.refresh(mix)
    return mix


def _published(db: Session, mix_id: int) -> Mix:
    mix = _get_or_404(db, mix_id)
    if mix.status != "published":
        raise HTTPException(status_code=404, detail="Published mix not found.")
    return mix


def _like(mix_id: int, enabled: bool, current_user: User, db: Session):
    _published(db, mix_id)
    mix_service.set_membership(db, MixLike, mix_id, current_user.id, enabled)
    return {
        "mix_id": mix_id,
        "is_liked": enabled,
        "like_count": mix_service.like_count(db, mix_id),
    }


@router.post("/{mix_id}/like")
@router.put("/{mix_id}/like", include_in_schema=False)
async def like_mix(mix_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    mix = _published(db, mix_id)
    was_liked = mix_service.liked_by(db, mix_id, current_user.id)
    result = _like(mix_id, True, current_user, db)
    if not was_liked and mix.owner_id is not None:
        notification = forum_service.notify(
            db,
            mix.owner_id,
            current_user.id,
            "mix_like",
            f"{current_user.username} liked your mix {mix.title}.",
            "mix",
            mix.id,
        )
        if notification:
            db.commit()
            db.refresh(notification)
            notification_payload = NotificationRead.model_validate(notification).model_dump(mode="json")
            await channel_hub.publish(f"user:{mix.owner_id}", "notification", notification_payload)
    return result


@router.delete("/{mix_id}/like")
def unlike_mix(mix_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _like(mix_id, False, current_user, db)


def _save(mix_id: int, enabled: bool, current_user: User, db: Session):
    _published(db, mix_id)
    mix_service.set_membership(db, SavedMix, mix_id, current_user.id, enabled)
    return {"mix_id": mix_id, "is_saved": enabled}


@router.post("/{mix_id}/save")
@router.put("/{mix_id}/save", include_in_schema=False)
def save_mix(mix_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _save(mix_id, True, current_user, db)


@router.delete("/{mix_id}/save")
def unsave_mix(mix_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _save(mix_id, False, current_user, db)
