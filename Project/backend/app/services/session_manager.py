"""Persistent, deterministic AI-DJ session behavior.

A DJSession persists a live SessionState: the current (feedback-mutated)
PromptIntent, which CandidateRetriever resolved it, and the resulting
now-playing/reasoning data. The real-time coaching feature ("more energy" /
"less vocals" / "smoother") mutates that stored intent using the same
deterministic keyword rules it always used, then re-runs the pipeline
against whichever CandidateRetriever originally served this session -- so it
works the same whether that retriever is the local catalog or Audius.
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.session import DJSession, SessionFeedback, UserPreference
from app.schemas import (
    NowPlayingRead,
    PromptIntent,
    ReasoningRead,
    SelectedSegment,
    SessionRead,
    Track,
)
from app.services.pipeline.dependencies import CANDIDATE_RETRIEVERS, get_vibe_understander
from app.services.pipeline.interfaces import (
    AudioRenderer,
    CandidateRetriever,
    SegmentSelector,
    TransitionPlanner,
    VibeUnderstander,
)
from app.services.pipeline.orchestrator import NoMatchingCandidate, retrieve_candidates
from app.services.pipeline_debug_service import notify_pipeline_debug_change

COVER_URL = "/brand/zonix-logo.svg"

_ENERGY_LEVELS = ["low", "medium", "high"]
_VOCALS_LEVELS = ["less", "neutral", "more"]

# Same descriptive copy the old hardcoded TRACKS dict used for each mood
# bucket; anything outside those 4 seeded buckets (an upload, an Audius
# track) gets a generic role label instead.
_ROLE_BY_BUCKET = {
    "energy": "Energy lift",
    "vocals": "Vocal center",
    "focus": "Low-distraction flow",
    "smooth": "Balanced opener",
}


def _normalize_feedback(feedback: str) -> str:
    value = feedback.strip().lower().replace(" ", "_")
    if "energy" in value:
        return "more_energy"
    if "vocal" in value:
        return "less_vocals"
    if "smooth" in value:
        return "smoother"
    if "good" in value or "like" in value:
        # Praise reinforces whatever is actually playing, rather than
        # teaching a generic preference that may contradict the session's
        # own context.
        return "reinforce"
    return "custom"


def _mutate_intent(intent: PromptIntent, normalized: str) -> tuple[PromptIntent, bool]:
    """Applies one coaching command to `intent`, using the same blunt jump
    the old track_key swap used (not a gradual nudge), so "more energy"
    reliably lands on the same kind of candidate every time. Returns the
    (possibly unchanged) intent and whether the planner should prefer a
    smoother transition."""

    data = intent.model_dump()
    if normalized == "more_energy":
        data["energy"] = "high"
    elif normalized == "less_vocals":
        data["energy"] = "low"
        data["vocals"] = "less"
    elif normalized == "smoother":
        return intent, True
    else:
        return intent, False
    return PromptIntent.model_validate(data), False


def _apply_preference(intent: PromptIntent, feedback: str) -> PromptIntent | None:
    """Turns one learned UserPreference row into an intent bias for a new
    session. Works purely in terms of Intent, so it applies no matter which
    CandidateRetriever ends up serving the biased intent (requirement 11)."""

    if feedback in ("more_energy", "less_vocals"):
        mutated, _ = _mutate_intent(intent, feedback)
        return mutated
    if feedback == "smoother":
        return intent  # "smooth" is already the deterministic default bucket
    if feedback.startswith("reinforce:"):
        parts = feedback.split(":", 2)
        if len(parts) == 3 and parts[1] in _ENERGY_LEVELS and parts[2] in _VOCALS_LEVELS:
            data = intent.model_dump()
            data["energy"], data["vocals"] = parts[1], parts[2]
            return PromptIntent.model_validate(data)
    return None


def _role_for(track: Track) -> str:
    return _ROLE_BY_BUCKET.get(track.vibe or "", "Now playing")


def _selected_moment_text(segment: SelectedSegment) -> str:
    where = (
        "the track's detected chorus/hook"
        if segment.method == "chorus_detection"
        else "the full clip"
    )
    return (
        f"Selected {segment.track.title} by {segment.track.artist} "
        f"({segment.start_second}s-{segment.end_second}s, {where})."
    )


def _next_direction(session: DJSession) -> str:
    if session.selected_feedback:
        return f"Applied {session.selected_feedback}; the selected moment and next transition now reflect it."
    return "Give feedback to steer energy, vocals, or transition smoothness."


def _resolve_and_render(
    db: Session,
    intent: PromptIntent,
    retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
    *,
    previous_segment: SelectedSegment | None,
    prefers_smoother: bool,
) -> tuple[Track, SelectedSegment, dict, dict, dict]:
    """Runs CandidateRetriever -> SegmentSelector -> TransitionPlanner ->
    AudioRenderer for one session-sized (single track) resolution and
    returns the pieces needed to persist SessionState, plus a pipeline_trace
    dict recording which concrete implementation handled each of those four
    stages and a short result from each -- read by the internal debug panel
    (routers/debug.py). The caller fills in the vibe_understander stage,
    since understand() may or may not have been called this resolution
    (feedback re-resolves without a new LLM call). Raises NoMatchingCandidate
    when the retriever plainly found nothing."""

    candidates = retrieve_candidates(db, intent, retriever, limit=5)
    track = candidates[0]
    segment = selector.select(db, track)
    transition = planner.plan(previous_segment, segment, prefers_smoother=prefers_smoother)
    rendered = renderer.render([segment], [transition])

    now_playing = {
        "title": track.title,
        "artist": track.artist,
        "album": track.album or "Zonix catalog",
        "cover_url": track.cover_url or COVER_URL,
        "role": _role_for(track),
        "audio_url": rendered.audio_url,
        "segment": segment.model_dump(mode="json"),
    }
    reasoning = {
        "selectedMoment": _selected_moment_text(segment),
        "transitionPlan": transition.notes,
    }
    pipeline_trace = {
        "candidate_retriever": {
            "implementation": type(retriever).__name__,
            "name": retriever.name,
            "candidate_count": len(candidates),
            "selected_track": {
                "source": track.source,
                "source_track_id": track.source_track_id,
                "title": track.title,
                "artist": track.artist,
            },
        },
        "segment_selector": {
            "implementation": type(selector).__name__,
            "method": segment.method,
            "start_second": segment.start_second,
            "end_second": segment.end_second,
            "bpm": segment.bpm,
            "musical_key": segment.musical_key,
        },
        "transition_planner": {
            "implementation": type(planner).__name__,
            "crossfade_ms": transition.crossfade_ms,
            "style": transition.style,
            "notes": transition.notes,
        },
        "audio_renderer": {
            "implementation": type(renderer).__name__,
            "is_pass_through": rendered.is_pass_through,
            "offset_count": len(rendered.offsets),
        },
        "resolved_at": utc_now().isoformat(),
    }
    return track, segment, now_playing, reasoning, pipeline_trace


def serialize_session(session: DJSession) -> SessionRead:
    now_playing = session.now_playing_json
    reasoning = session.reasoning_json
    return SessionRead(
        id=session.id,
        prompt=session.prompt,
        status=session.status,
        vibeLabel=session.vibe_label,
        audioUrl=now_playing["audio_url"],
        nowPlaying=NowPlayingRead(
            title=now_playing["title"],
            artist=now_playing["artist"],
            album=now_playing["album"],
            coverUrl=now_playing["cover_url"],
            vibeLabel=session.vibe_label,
            role=now_playing["role"],
        ),
        reasoning=ReasoningRead(
            selectedMoment=reasoning["selectedMoment"],
            transitionPlan=reasoning["transitionPlan"],
            nextDirection=_next_direction(session),
        ),
        selectedFeedback=session.selected_feedback,
    )


def _initial_intent(
    prompt: str, db: Session, user_id: int | None, vibe: VibeUnderstander
) -> PromptIntent:
    intent = vibe.understand(prompt)
    is_neutral = intent.energy == "medium" and intent.vocals == "neutral" and not intent.artist
    if is_neutral and user_id is not None:
        preferences = (
            db.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.score > 0)
            .order_by(UserPreference.score.desc(), UserPreference.count.desc())
            .all()
        )
        for preference in preferences:
            biased = _apply_preference(intent, preference.feedback)
            if biased is not None:
                return biased
    return intent


def create_session(
    db: Session,
    prompt: str,
    user_id: int | None,
    *,
    vibe: VibeUnderstander,
    retriever: CandidateRetriever,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> SessionRead:
    intent = _initial_intent(prompt, db, user_id, vibe)
    _, _, now_playing, reasoning, pipeline_trace = _resolve_and_render(
        db, intent, retriever, selector, planner, renderer,
        previous_segment=None, prefers_smoother=False,
    )
    pipeline_trace["vibe_understander"] = {
        "implementation": type(vibe).__name__,
        "invoked": True,
        "intent": intent.model_dump(mode="json"),
    }

    session = DJSession(
        id=f"session_{uuid4().hex}",
        user_id=user_id,
        prompt=prompt,
        status="playing",
        vibe_label=now_playing["segment"]["track"]["vibe_label"] or "Balanced opener",
        retriever_name=retriever.name,
        intent_json=intent.model_dump(mode="json"),
        now_playing_json=now_playing,
        reasoning_json=reasoning,
        pipeline_trace_json=pipeline_trace,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    notify_pipeline_debug_change()
    return serialize_session(session)


def get_session(db: Session, session_id: str) -> DJSession | None:
    return db.query(DJSession).filter(DJSession.id == session_id).first()


def apply_feedback(
    db: Session,
    session: DJSession,
    feedback: str,
    *,
    selector: SegmentSelector,
    planner: TransitionPlanner,
    renderer: AudioRenderer,
) -> SessionRead:
    current_intent = PromptIntent.model_validate(session.intent_json)
    normalized = _normalize_feedback(feedback)
    session.selected_feedback = feedback
    db.add(
        SessionFeedback(
            session_id=session.id,
            user_id=session.user_id,
            feedback=feedback,
            normalized_feedback=normalized,
        )
    )

    preference_key: str | None = None
    if normalized in ("more_energy", "less_vocals", "smoother"):
        mutated, prefers_smoother = _mutate_intent(current_intent, normalized)
        preference_key = normalized
    elif normalized == "reinforce":
        mutated, prefers_smoother = current_intent, False
        preference_key = f"reinforce:{current_intent.energy}:{current_intent.vocals}"
    else:
        mutated, prefers_smoother = current_intent, False

    resolved_again = False
    if mutated is not current_intent or prefers_smoother:
        retriever = CANDIDATE_RETRIEVERS[session.retriever_name]
        previous_segment = SelectedSegment.model_validate(session.now_playing_json["segment"])
        try:
            _, _, now_playing, reasoning, pipeline_trace = _resolve_and_render(
                db, mutated, retriever, selector, planner, renderer,
                previous_segment=previous_segment, prefers_smoother=prefers_smoother,
            )
            # Feedback mutates the stored intent with fixed keyword rules
            # (_mutate_intent) rather than calling the LLM again -- invoked
            # stays False so the debug panel doesn't imply a call that never
            # happened, while still naming which implementation is bound.
            pipeline_trace["vibe_understander"] = {
                "implementation": type(get_vibe_understander()).__name__,
                "invoked": False,
                "intent": mutated.model_dump(mode="json"),
            }
            session.intent_json = mutated.model_dump(mode="json")
            session.now_playing_json = now_playing
            session.reasoning_json = reasoning
            session.pipeline_trace_json = pipeline_trace
            session.vibe_label = now_playing["segment"]["track"]["vibe_label"] or session.vibe_label
            resolved_again = True
        except NoMatchingCandidate:
            # Nothing matched the mutated intent closely enough; keep the
            # session on its current track rather than erroring out a live
            # session over one bad feedback mutation.
            pass

    if session.user_id is not None and preference_key is not None:
        preference = (
            db.query(UserPreference)
            .filter_by(user_id=session.user_id, feedback=preference_key)
            .first()
        )
        if preference is None:
            preference = UserPreference(
                user_id=session.user_id, feedback=preference_key, count=0, score=0
            )
            db.add(preference)
        preference.count += 1
        preference.score += 1

    db.commit()
    db.refresh(session)
    if resolved_again:
        notify_pipeline_debug_change()
    return serialize_session(session)


def stop_session(db: Session, session: DJSession) -> dict:
    session.status = "stopped"
    db.commit()
    return {"session_id": session.id, "status": "stopped", "message": "AI DJ session stopped."}
