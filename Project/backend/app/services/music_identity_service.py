"""Deterministic Music Identity analytics over raw listening events.

This module intentionally stops at factual aggregation. The future Listening
DNA/ML implementation can populate UserMusicProfile.dna_* without changing the
frontend/API contract.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.mix import Mix
from app.database.models.music_identity import ListeningEvent, UserMusicProfile
from app.database.models.session import DJSession

PERIODS = {"7d": 7, "30d": 30, "6m": 183, "all": None}


def get_or_create_music_profile(db: Session, user_id: int) -> UserMusicProfile:
    profile = db.query(UserMusicProfile).filter(UserMusicProfile.user_id == user_id).first()
    if profile is None:
        profile = UserMusicProfile(user_id=user_id, is_public=False, visibility="private")
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def set_visibility(profile: UserMusicProfile, visibility: str) -> None:
    profile.visibility = visibility
    # Keep the original boolean synchronized for older clients/migrations.
    profile.is_public = visibility == "public"


def _aggregate_named(events: list[ListeningEvent], attribute: str) -> dict[str, tuple[str, int]]:
    values: dict[str, list] = {}
    for event in events:
        raw = getattr(event, attribute, None)
        if not isinstance(raw, str) or not raw.strip() or event.seconds_listened <= 0:
            continue
        name = raw.strip()
        key = name.casefold()
        if key not in values:
            values[key] = [name, 0]
        values[key][1] += int(event.seconds_listened)
    return {key: (str(value[0]), int(value[1])) for key, value in values.items()}


def _metrics(grouped: dict[str, tuple[str, int]], denominator: int) -> list[dict]:
    items = sorted(grouped.values(), key=lambda item: (-item[1], item[0].casefold()))
    denominator = max(0, denominator)
    return [
        {
            "name": name,
            "seconds": seconds,
            "percentage": round((seconds / denominator) * 100, 1) if denominator else 0.0,
        }
        for name, seconds in items
    ]


def _tracks(events: list[ListeningEvent], denominator: int) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for event in events:
        if event.seconds_listened <= 0:
            continue
        key = (
            event.source,
            event.source_track_id or f"{event.artist_name.casefold()}::{event.track_title.casefold()}",
        )
        item = grouped.setdefault(
            key,
            {"title": event.track_title, "artist": event.artist_name, "seconds": 0},
        )
        item["seconds"] += int(event.seconds_listened)
    ordered = sorted(grouped.values(), key=lambda item: (-item["seconds"], item["title"].casefold()))
    return [
        {
            **item,
            "percentage": round(item["seconds"] / denominator * 100, 1) if denominator else 0.0,
        }
        for item in ordered[:12]
    ]


def _time_of_day(events: list[ListeningEvent], denominator: int) -> list[dict]:
    buckets = {"Morning": 0, "Afternoon": 0, "Evening": 0, "Night": 0}
    for event in events:
        hour = event.started_at.hour
        if 5 <= hour < 12:
            bucket = "Morning"
        elif 12 <= hour < 17:
            bucket = "Afternoon"
        elif 17 <= hour < 22:
            bucket = "Evening"
        else:
            bucket = "Night"
        buckets[bucket] += max(0, int(event.seconds_listened))
    return [
        {"name": name, "seconds": seconds, "percentage": round(seconds / denominator * 100, 1) if denominator else 0.0}
        for name, seconds in buckets.items()
        if seconds > 0
    ]


def _dna(profile: UserMusicProfile) -> dict:
    dimensions: list[dict] = []
    features = profile.dna_features
    if isinstance(features, dict):
        for name, value in features.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                dimensions.append({"name": str(name), "value": max(0.0, min(1.0, float(value)))})
    elif isinstance(features, list):
        for item in features:
            if not isinstance(item, dict):
                continue
            name, value = item.get("name"), item.get("value")
            if isinstance(name, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                dimensions.append({"name": name, "value": max(0.0, min(1.0, float(value)))})
    return {
        "status": profile.dna_status,
        "label": profile.dna_label,
        "summary": profile.dna_summary,
        "dimensions": dimensions,
        "version": profile.dna_version,
    }


def _trend(events: list[ListeningEvent], period: str) -> list[dict]:
    if not events:
        return []
    if period in {"7d", "30d"}:
        listened: dict[date, int] = defaultdict(int)
        for event in events:
            listened[event.started_at.date()] += max(0, int(event.seconds_listened))
        end = max(listened)
        count = PERIODS[period] or 30
        start = end - timedelta(days=count - 1)
        points = []
        day = start
        while day <= end:
            points.append({"date": day.isoformat(), "seconds": listened.get(day, 0)})
            day += timedelta(days=1)
        return points
    if period == "6m":
        listened: dict[date, int] = defaultdict(int)
        for event in events:
            day = event.started_at.date()
            week = day - timedelta(days=day.weekday())
            listened[week] += max(0, int(event.seconds_listened))
        return [{"date": key.isoformat(), "seconds": listened[key]} for key in sorted(listened)]
    listened_month: dict[str, int] = defaultdict(int)
    for event in events:
        listened_month[event.started_at.strftime("%Y-%m-01")] += max(0, int(event.seconds_listened))
    return [{"date": key, "seconds": listened_month[key]} for key in sorted(listened_month)]


def _recent_listening(db: Session, events: list[ListeningEvent], limit: int = 6) -> list[dict]:
    grouped: dict[str, dict] = {}
    for event in events:
        if event.mix_id is not None:
            key, kind = f"mix:{event.mix_id}", "mix"
        elif event.session_id:
            key, kind = f"session:{event.session_id}", "session"
        else:
            continue
        item = grouped.setdefault(key, {"key": key, "kind": kind, "seconds": 0, "started_at": event.started_at})
        item["seconds"] += int(event.seconds_listened)
        if event.started_at > item["started_at"]:
            item["started_at"] = event.started_at

    ordered = sorted(grouped.values(), key=lambda item: item["started_at"], reverse=True)[:limit]
    result = []
    for item in ordered:
        context_id = item["key"].split(":", 1)[1]
        title = "Cuemix listening session"
        subtitle = None
        if item["kind"] == "mix":
            mix = db.query(Mix).filter(Mix.id == int(context_id)).first()
            if mix:
                title, subtitle = mix.title, mix.prompt
        else:
            session = db.query(DJSession).filter(DJSession.id == context_id).first()
            if session:
                title, subtitle = session.vibe_label, session.prompt
        result.append({**item, "title": title, "subtitle": subtitle})
    return result


def _filter_events(db: Session, user_id: int, period: str) -> list[ListeningEvent]:
    query = db.query(ListeningEvent).filter(ListeningEvent.user_id == user_id)
    days = PERIODS.get(period)
    if period not in PERIODS:
        period = "all"
        days = None
    if days:
        query = query.filter(ListeningEvent.started_at >= utc_now() - timedelta(days=days))
    return query.order_by(ListeningEvent.started_at.desc(), ListeningEvent.id.desc()).all()


def build_music_identity(db: Session, user_id: int, period: str = "all") -> dict:
    if period not in PERIODS:
        period = "all"
    music_profile = get_or_create_music_profile(db, user_id)
    events = _filter_events(db, user_id, period)
    total_seconds = sum(max(0, int(event.seconds_listened)) for event in events)

    artists_grouped = _aggregate_named(events, "artist_name")
    genres_grouped = _aggregate_named(events, "genre")
    vibes_grouped = _aggregate_named(events, "vibe")
    known_genre_seconds = sum(seconds for _, seconds in genres_grouped.values())
    known_vibe_seconds = sum(seconds for _, seconds in vibes_grouped.values())
    artists = _metrics(artists_grouped, total_seconds)
    genres = _metrics(genres_grouped, known_genre_seconds)
    vibes = _metrics(vibes_grouped, known_vibe_seconds)
    contexts = _recent_listening(db, events, limit=1000)

    return {
        "is_public": music_profile.visibility == "public",
        "visibility": music_profile.visibility,
        "period": period,
        "summary": {
            "total_listening_seconds": total_seconds,
            "top_artist": artists[0] if artists else None,
            "top_genre": genres[0] if genres else None,
            "top_vibe": vibes[0] if vibes else None,
            "artists_discovered": len(artists_grouped),
            "tracks_discovered": len({
                (event.source, event.source_track_id or f"{event.artist_name.casefold()}::{event.track_title.casefold()}")
                for event in events if event.seconds_listened > 0
            }),
            "listening_contexts": len(contexts),
            "average_context_seconds": round(sum(item["seconds"] for item in contexts) / len(contexts)) if contexts else 0,
        },
        "artists": artists[:12],
        "genres": genres[:12],
        "vibes": vibes[:12],
        "top_tracks": _tracks(events, total_seconds),
        "time_of_day": _time_of_day(events, total_seconds),
        "listening_trend": _trend(events, period),
        "recent_listening": contexts[:6],
        "listening_dna": _dna(music_profile),
    }
