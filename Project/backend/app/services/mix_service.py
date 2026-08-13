"""Business logic for generated, persisted, and social mixes.

Routed through the same pipeline sessions use (VibeUnderstander ->
CandidateRetriever -> SegmentSelector -> TransitionPlanner -> AudioRenderer);
mixes default to the Audius retriever with the local catalog as a safety net,
matching this surface's existing behavior (old local_demo_track() fallback).
"""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike, SavedMix
from app.schemas import PromptIntent, SelectedSegment, Track, TransitionPlan
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)

MAX_MIX_TRACKS = 5


def _retrieve_with_fallback(
    db: Session,
    intent: PromptIntent,
    retriever: CandidateRetriever,
    catalog_fallback: CandidateRetriever,
    *,
    limit: int,
) -> list[Track]:
    """Mixes must never hard-fail the way a session can plainly report "no
    match": this mirrors the old local_demo_track() safety net, just backed
    by the real catalog instead of one hardcoded dict."""

    tracks = retriever.retrieve(db, intent, limit=limit)
    if tracks:
        return tracks
    tracks = catalog_fallback.retrieve(db, intent, limit=1)
    if tracks:
        return tracks
    # Absolute last resort: drop any artist filter so an unmatched named
    # artist still resolves to *something* playable for a mix.
    neutral_intent = intent.model_copy(update={"artist": None})
    return catalog_fallback.retrieve(db, neutral_intent, limit=1)


def _plan_transitions(
    segments: list[SelectedSegment], planner: TransitionPlanner
) -> list[TransitionPlan]:
    return [
        planner.plan(segments[index], segments[index + 1], prefers_smoother=False)
        for index in range(len(segments) - 1)
    ]


def create_mix(
    db: Session,
    prompt: str,
    owner_id: int | None,
    *,
    vibe: VibeUnderstander,
    retriever: CandidateRetriever,
    catalog_fallback: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> Mix:
    intent = vibe.understand(prompt)
    tracks = _retrieve_with_fallback(
        db, intent, retriever, catalog_fallback, limit=MAX_MIX_TRACKS
    )

    segments = [selector.select(db, track) for track in tracks]
    transitions = _plan_transitions(segments, planner)
    rendered = renderer.render(segments, transitions)

    # A composite render carries a real offset per input segment; a
    # pass-through only ever safely describes one track's worth of audio.
    kept_segments = segments if not rendered.is_pass_through else segments[:1]
    offsets = rendered.offsets if not rendered.is_pass_through else rendered.offsets[:1]

    session_id = f"mix_{uuid4().hex}"
    mix = Mix(
        session_id=session_id,
        owner_id=owner_id,
        title=prompt[:120],
        prompt=prompt,
        status="draft",
        cover_url=tracks[0].cover_url,
    )
    db.add(mix)
    try:
        db.flush()
        position = 0
        for index, (segment, (start_second, end_second)) in enumerate(zip(kept_segments, offsets)):
            if end_second <= start_second:
                continue
            position += 1
            track = segment.track
            db.add(
                MixSegment(
                    mix_id=mix.id,
                    position=position,
                    title=track.title[:255],
                    artist=track.artist[:255],
                    audio_url=rendered.audio_url,
                    cover_url=track.cover_url,
                    start_second=start_second,
                    end_second=end_second,
                    transition_to_next=(
                        "crossfade"
                        if not rendered.is_pass_through and index < len(kept_segments) - 1
                        else "end"
                    ),
                    source=track.source[:50],
                    source_track_id=str(track.source_track_id)[:255],
                    genre=(track.genre or None),
                    vibe=(track.vibe_label or track.vibe or intent.mood or None),
                )
            )
        db.commit()
        db.refresh(mix)
    except Exception:
        db.rollback()
        raise
    return mix


def get_mix(db: Session, mix_id: int) -> Mix | None:
    return (
        db.query(Mix)
        .options(selectinload(Mix.segments), selectinload(Mix.owner))
        .filter(Mix.id == mix_id)
        .first()
    )


def set_membership(db: Session, model, mix_id: int, user_id: int, enabled: bool) -> None:
    existing = db.query(model).filter_by(mix_id=mix_id, user_id=user_id).first()
    if enabled and existing is None:
        try:
            db.add(model(mix_id=mix_id, user_id=user_id))
            db.commit()
        except IntegrityError:
            db.rollback()
    elif not enabled and existing is not None:
        db.delete(existing)
        db.commit()


def like_count(db: Session, mix_id: int) -> int:
    return db.query(MixLike).filter(MixLike.mix_id == mix_id).count()


def liked_by(db: Session, mix_id: int, user_id: int | None) -> bool:
    return bool(
        user_id is not None
        and db.query(MixLike).filter_by(mix_id=mix_id, user_id=user_id).first()
    )


def saved_by(db: Session, mix_id: int, user_id: int | None) -> bool:
    return bool(
        user_id is not None
        and db.query(SavedMix).filter_by(mix_id=mix_id, user_id=user_id).first()
    )
