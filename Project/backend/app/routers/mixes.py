"""Generated mix API and its public feed/private library."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    MixUpdate,
    StartMixRequest,
)
from app.services import mix_service

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
):
    """Create a persisted mix; provider failures use the known local demo."""

    return mix_service.create_mix(db, request.prompt, current_user.id if current_user else None)


@router.get("/feed", response_model=list[MixFeedItem])
def get_feed(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    mixes = (
        db.query(Mix)
        .options(selectinload(Mix.owner), selectinload(Mix.segments))
        .filter(Mix.status == "published", Mix.owner_id.is_not(None))
        .order_by(Mix.published_at.desc(), Mix.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_feed_item(db, mix, current_user.id if current_user else None) for mix in mixes]


@router.get("/library", response_model=MixLibraryRead)
def get_library(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    owned = (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .filter(Mix.owner_id == current_user.id)
        .order_by(Mix.created_at.desc())
        .all()
    )
    saved = (
        db.query(Mix)
        .options(selectinload(Mix.segments))
        .join(SavedMix, SavedMix.mix_id == Mix.id)
        .filter(SavedMix.user_id == current_user.id, Mix.status == "published")
        .order_by(SavedMix.created_at.desc())
        .all()
    )
    return {"owned": owned, "saved": saved}


@router.get("/mine", response_model=list[MixRead])
def get_owned(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_library(current_user, db).get("owned", [])


@router.get("/saved", response_model=list[MixRead])
def get_saved(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_library(current_user, db).get("saved", [])


@router.get("/{mix_id}", response_model=MixRead)
def read_mix(mix_id: int, db: Session = Depends(get_db)):
    mix = _get_or_404(db, mix_id)
    if mix.status != "published":
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
def like_mix(mix_id: int, _: None = Depends(write_rate_limit), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _like(mix_id, True, current_user, db)


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
