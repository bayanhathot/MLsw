"""Realistic cold-seed dataset generator.

Populates a fresh database so it looks like roughly 50 real listeners have
been using Cuemix for months: accounts, profiles, listening history, a
social graph, forum activity, direct messages, mixes, and DJ sessions --
built through the same SQLAlchemy models (and, wherever the existing
service layer's business rule is the right thing to reuse rather than
duplicate -- friendship ordering, notification creation, prompt-shortcut
clustering -- the same service functions) every real request path uses.
Nothing here calls into the AI-DJ pipeline itself (VibeUnderstander/
CandidateRetriever/AudioRenderer): that would mean real network calls or
audio rendering per row for hundreds of rows, so DJSession/Mix/
ListeningEvent rows are built directly in the pipeline's own output shape
instead (see _fake_intent/_build_now_playing) -- same contract, no
network/Ollama/Audius dependency.

Playable audio: every seeded Mix segment and DJSession "now playing" points
at one of the four real catalog tracks the app already ships (migration-
seeded, see catalog_retriever.py) via GET /catalog/tracks/{id}/audio --
staged onto disk up front by this module the same way the pipeline stages
it lazily on first real use, so seeded sessions/mixes are actually playable
immediately rather than 404ing until a real resolution happens to run
first. Displayed title/artist/genre are still this seed's own rich,
per-segment fictional data -- only the underlying audio *file* is shared,
the same way the four real seed tracks already share one file today.

Idempotency: gated by a ColdSeedRun row keyed on the version string (see
config.py) -- a fast, indexed lookup that skips the whole run on every
redeploy after the first. Nothing below commits until the very end (the
same transaction that writes the ColdSeedRun marker), so a failure partway
through rolls back completely instead of leaving partial, undetectable
duplicate data for the next run to double up on.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import public_api_url
from app.core.security import hash_password
from app.core.time import utc_now
from app.database.models.attachment import Attachment
from app.database.models.catalog import CatalogTrack
from app.database.models.forum import ForumComment, ForumCommentVote, ForumPost, ForumPostVote
from app.database.models.messaging import DirectMessage, Notification
from app.database.models.mix import Mix, MixSegment
from app.database.models.mix_social import MixLike, SavedMix
from app.database.models.music_identity import ListeningEvent, UserMusicProfile
from app.database.models.profile import Profile
from app.database.models.seed_state import ColdSeedRun
from app.database.models.session import DJSession, PromptShortcut, SessionFeedback, UserPreference
from app.database.models.social import FriendRequest, Friendship, UserBlock
from app.database.models.user import User
from app.schemas import PromptIntent
from app.services import forum_service, prompt_shortcuts, social_service, upload_queue
from app.services.pipeline.catalog_retriever import (
    CATALOG_AUDIO_SUBDIR,
    _ensure_seed_catalog,
    _SEED_AUDIO_SOURCE,
)

from app.coldseed import content

TARGET_USER_COUNT = 50
PUBLIC_PROFILE_RATIO = 0.7


@dataclass
class SeededUser:
    user: User
    genres: list[str]
    vibe: str
    mood: str
    is_public: bool
    joined_at: datetime


@dataclass
class Counters:
    """Running totals surfaced in the final summary + used for deterministic
    unique keys (client_event_id, attachment storage names) within one run."""

    listening_events: int = 0
    attachments: int = 0
    notifications: int = 0


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _random_activity_time(rng: random.Random, floor: datetime, ceiling: datetime) -> datetime:
    """A uniformly-random timestamp in [floor, ceiling], clamped so activity
    never lands before its own prerequisite (account creation, the post it
    replies to, ...) or after "now"."""

    if floor >= ceiling:
        return ceiling
    span_seconds = int((ceiling - floor).total_seconds())
    return floor + timedelta(seconds=rng.randint(0, span_seconds))


def _bias_hour(
    rng: random.Random, dt: datetime, seeded_user: SeededUser, floor: datetime, ceiling: datetime
) -> datetime:
    """Gives each user a consistent (deterministic from their id), slightly
    fuzzy preferred hour-of-day, so per-user "time of day" analytics
    actually vary by listener instead of being uniformly random noise.
    Re-clamped to [floor, ceiling] afterward: replacing just the hour can
    otherwise push a timestamp that started on `floor`'s own calendar day
    earlier than `floor` itself (e.g. a join-day event biased to an hour
    before the user actually joined)."""

    preferred_hour = (seeded_user.user.id * 7) % 24
    hour = int(rng.gauss(preferred_hour, 3)) % 24
    biased = dt.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
    return max(floor, min(biased, ceiling))


def _finalize_notification(
    rng: random.Random,
    notification: Notification | None,
    created_at: datetime,
    now: datetime,
    counters: Counters,
) -> None:
    """forum_service.notify() (reused as-is, see its own docstring) doesn't
    commit or timestamp -- this backdates the notification to match the
    seeded action it belongs to and gives it a realistic read/unread state
    (older notifications are more likely to have been seen)."""

    if notification is None:
        return
    notification.created_at = created_at
    is_old = created_at < now - timedelta(days=2)
    notification.is_read = is_old and rng.random() < 0.75
    counters.notifications += 1


def _fake_intent(rng: random.Random, mood: str, genres: list[str]) -> dict:
    """A PromptIntent-shaped dict good enough to satisfy the real schema
    (validated by tests) without ever calling the real VibeUnderstander --
    this seed is offline by design, see module docstring."""

    energy = rng.choice(["low", "medium", "high"])
    vocals = rng.choice(["less", "neutral", "more"])
    genre = genres[0] if genres else rng.choice(content.GENRES)
    search_query = f"{mood} {genre.lower()} mix"[:120]
    return {
        "mood": mood[:40],
        "energy": energy,
        "vocals": vocals,
        "genres": genres[:5],
        "artist": None,
        "artist_mode": "none",
        "search_query": search_query,
    }


def _demo_catalog_audio_url(catalog_track_id: int) -> str:
    return public_api_url(f"/catalog/tracks/{catalog_track_id}/audio")


def _build_now_playing(rng: random.Random, genre: str, vibe: str, catalog_track_id: int) -> dict:
    """A now_playing/segment/track dict matching exactly what
    session_manager._resolve_and_render's real output shape is (and what
    NowPlayingRead/SelectedSegment/Track validate) -- a live session/advance
    call against a seeded row must never hit a pydantic ValidationError."""

    artist = rng.choice(content.ARTISTS_BY_GENRE[genre])
    title = f"{rng.choice(content.TRACK_TITLE_ADJECTIVES)} {rng.choice(content.TRACK_TITLE_NOUNS)}"
    duration = rng.randint(150, 260)
    end_second = min(45, duration)
    track = {
        "source": "catalog",
        "source_track_id": str(catalog_track_id),
        "title": title,
        "artist": artist,
        "album": f"{artist} Sessions",
        "audio_url": _demo_catalog_audio_url(catalog_track_id),
        "cover_url": None,
        "duration_seconds": duration,
        "genre": genre,
        "vibe": vibe,
        "vibe_label": vibe.title(),
        "tags": None,
        "catalog_track_id": catalog_track_id,
        "local_path": None,
    }
    segment = {
        "track": track,
        "start_second": 0,
        "end_second": end_second,
        "method": "whole_clip",
        "bpm": round(rng.uniform(85, 140), 1),
        "musical_key": rng.choice(["C maj", "A min", "G maj", "E min", "D maj", "F# min"]),
    }
    now_playing = {
        "title": title,
        "artist": artist,
        "album": track["album"],
        "cover_url": "/brand/cuemix-logo.svg",
        "role": "Now playing",
        "audio_url": track["audio_url"],
        "segment": segment,
    }
    return now_playing


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _build_placeholder_png(rgb: tuple[int, int, int], size: int = 8) -> bytes:
    """A genuinely valid, tiny PNG (not a fake/broken image) built from pure
    stdlib (struct + zlib) -- no external asset or network fetch, so
    attachment images actually render in a browser instead of showing a
    broken-image icon."""

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * size
    raw = row * size
    idat = zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _pick_unique_name(rng: random.Random, used_names: set[tuple[str, str]]) -> tuple[str, str]:
    while True:
        first = rng.choice(content.FIRST_NAMES)
        last = rng.choice(content.LAST_NAMES)
        if (first, last) not in used_names:
            used_names.add((first, last))
            return first, last


def _username_for(first: str, last: str, rng: random.Random, used_usernames: set[str]) -> str:
    styles = [
        f"{first.lower()}.{last.lower()}",
        f"{first.lower()}{last.lower()}",
        f"{first.lower()}_{last.lower()}",
        f"{first[0].lower()}{last.lower()}",
        f"{first.lower()}.{last[0].lower()}",
    ]
    rng.shuffle(styles)
    for base in styles:
        candidate = base[:45]
        if candidate not in used_usernames:
            used_usernames.add(candidate)
            return candidate
    for _ in range(50):
        candidate = f"{styles[0][:42]}{rng.randint(10, 99)}"
        if candidate not in used_usernames:
            used_usernames.add(candidate)
            return candidate
    raise RuntimeError("Exhausted cold-seed username generation attempts.")


# ---------------------------------------------------------------------------
# Phase 1: users, profiles, music-identity visibility
# ---------------------------------------------------------------------------


def _seed_users(db: Session, rng: random.Random, version: str, now: datetime) -> list[SeededUser]:
    """Builds all TARGET_USER_COUNT User rows first and flushes exactly
    once (rather than once per user) to assign their ids, then builds every
    dependent Profile/UserMusicProfile row against those now-known ids --
    one flush instead of TARGET_USER_COUNT is the difference between this
    phase taking a fraction of a second and taking several seconds."""

    used_names: set[tuple[str, str]] = set()
    used_usernames: set[str] = set()
    public_count = round(TARGET_USER_COUNT * PUBLIC_PROFILE_RATIO)

    planned: list[tuple[User, str, str, list[str], str, str, bool, datetime]] = []
    for index in range(TARGET_USER_COUNT):
        first, last = _pick_unique_name(rng, used_names)
        username = _username_for(first, last, rng, used_usernames)
        joined_at = now - timedelta(days=rng.randint(30, 195), hours=rng.randint(0, 23))

        user = User(
            username=username,
            # ".invalid" (RFC 2606) is the more conventional choice for
            # obviously-fake addresses, but pydantic's EmailStr (via
            # email_validator) rejects it outright as a "special-use
            # domain" -- on *both* /auth/register and /auth/login, since
            # both schemas use EmailStr -- which would make every seeded
            # account permanently unable to log in through the real
            # endpoint. ".example" (also RFC 2606-reserved, also never
            # real mail) passes validation, so seeded accounts stay
            # actually usable.
            email=f"{username}@coldseed.cuemix.example",
            hashed_password=hash_password(f"coldseed-{version}-{username}"),
            is_active=True,
            created_at=joined_at,
        )
        db.add(user)

        genres = rng.sample(content.GENRES, k=rng.randint(2, 4))
        vibe = rng.choice(content.VIBE_PHRASES)
        mood = rng.choice(content.MOODS)
        is_public = index < public_count
        planned.append((user, first, last, genres, vibe, mood, is_public, joined_at))

    db.flush()  # assigns .id to every planned user at once

    seeded: list[SeededUser] = []
    for user, first, last, genres, vibe, mood, is_public, joined_at in planned:
        bio_template = rng.choice(content.BIO_TEMPLATES)
        bio = (
            bio_template.format(genre1=genres[0], genre2=genres[-1], vibe=vibe)
            if bio_template
            else None
        )
        db.add(
            Profile(
                user_id=user.id,
                display_name=f"{first} {last}",
                bio=bio,
                favorite_genres=genres,
                theme_preference=rng.choice(["dark", "dark", "dark", "light", "system"]),
                created_at=joined_at,
            )
        )

        if is_public:
            visibility = "friends" if rng.random() < 0.12 else "public"
        else:
            visibility = "private"
        db.add(
            UserMusicProfile(
                user_id=user.id,
                is_public=visibility == "public",
                visibility=visibility,
                created_at=joined_at,
                updated_at=joined_at,
            )
        )

        seeded.append(
            SeededUser(user=user, genres=genres, vibe=vibe, mood=mood, is_public=is_public, joined_at=joined_at)
        )

    # Shuffles processing order for every later phase without changing which
    # users landed in the public/private cohort above.
    rng.shuffle(seeded)
    return seeded


# ---------------------------------------------------------------------------
# Phase 2: social graph -- friend requests, friendships, blocks
# ---------------------------------------------------------------------------


def _seed_social_graph(
    db: Session, rng: random.Random, seeded: list[SeededUser], now: datetime, counters: Counters
) -> dict[int, set[int]]:
    friend_pairs: set[frozenset[int]] = set()
    friends_of: dict[int, set[int]] = {s.user.id: set() for s in seeded}

    for seeded_user in seeded:
        target = rng.randint(3, 14)
        candidates = [s for s in seeded if s.user.id != seeded_user.user.id]
        rng.shuffle(candidates)
        made = 0
        for candidate in candidates:
            if made >= target:
                break
            pair = frozenset((seeded_user.user.id, candidate.user.id))
            if pair in friend_pairs or len(friends_of[candidate.user.id]) >= 16:
                continue
            friend_pairs.add(pair)
            friends_of[seeded_user.user.id].add(candidate.user.id)
            friends_of[candidate.user.id].add(seeded_user.user.id)
            made += 1

            sender, receiver = (candidate, seeded_user) if rng.random() < 0.5 else (seeded_user, candidate)
            requested_at = min(
                max(sender.joined_at, receiver.joined_at) + timedelta(days=rng.randint(0, 30), hours=rng.randint(0, 23)),
                now,
            )
            responded_at = min(requested_at + timedelta(hours=rng.randint(1, 72)), now)

            db.add(
                FriendRequest(
                    sender_id=sender.user.id, receiver_id=receiver.user.id,
                    status="accepted", created_at=requested_at, responded_at=responded_at,
                )
            )
            a, b = social_service.ordered_pair(sender.user.id, receiver.user.id)
            db.add(Friendship(user_a_id=a, user_b_id=b, created_at=responded_at))

            _finalize_notification(
                rng,
                forum_service.notify(
                    db, receiver.user.id, sender.user.id, "friend_request",
                    f"{sender.user.username} sent you a friend request.", "user", sender.user.id,
                ),
                requested_at, now, counters,
            )
            _finalize_notification(
                rng,
                forum_service.notify(
                    db, sender.user.id, receiver.user.id, "friend_accepted",
                    f"{receiver.user.username} accepted your friend request.", "user", receiver.user.id,
                ),
                responded_at, now, counters,
            )

    # A handful of unanswered/declined requests too -- every friendship above
    # already produced an "accepted" one, this just adds the messier, more
    # realistic in-between states a real social graph has.
    requested_undirected = set(friend_pairs)
    attempts = 0
    while attempts < 24:
        attempts += 1
        sender, receiver = rng.sample(seeded, k=2)
        pair = frozenset((sender.user.id, receiver.user.id))
        if pair in requested_undirected:
            continue
        requested_undirected.add(pair)
        requested_at = min(
            max(sender.joined_at, receiver.joined_at) + timedelta(days=rng.randint(0, 60)), now
        )
        status = "declined" if rng.random() < 0.3 else "pending"
        responded_at = None
        if status == "declined":
            responded_at = min(requested_at + timedelta(hours=rng.randint(1, 48)), now)
        db.add(
            FriendRequest(
                sender_id=sender.user.id, receiver_id=receiver.user.id,
                status=status, created_at=requested_at, responded_at=responded_at,
            )
        )
        _finalize_notification(
            rng,
            forum_service.notify(
                db, receiver.user.id, sender.user.id, "friend_request",
                f"{sender.user.username} sent you a friend request.", "user", sender.user.id,
            ),
            requested_at, now, counters,
        )

    # A few blocks between non-friends, for the safety-feature surface.
    blocked_pairs: set[frozenset[int]] = set()
    attempts = 0
    while len(blocked_pairs) < 6 and attempts < 60:
        attempts += 1
        blocker, blocked = rng.sample(seeded, k=2)
        pair = frozenset((blocker.user.id, blocked.user.id))
        if pair in friend_pairs or pair in blocked_pairs:
            continue
        blocked_pairs.add(pair)
        blocked_at = min(max(blocker.joined_at, blocked.joined_at) + timedelta(days=rng.randint(1, 90)), now)
        db.add(UserBlock(blocker_id=blocker.user.id, blocked_id=blocked.user.id, created_at=blocked_at))

    return friends_of


# ---------------------------------------------------------------------------
# Phase 3: extra catalog tracks + staging the shared demo audio file
# ---------------------------------------------------------------------------


def _stage_demo_audio() -> None:
    """Every seeded Mix segment / DJSession points at one of the 4 real
    catalog tracks' /catalog/tracks/{id}/audio endpoint; that route 404s
    until the file is actually staged on disk. The real pipeline stages it
    lazily on first genuine resolution (catalog_retriever._ensure_local_file);
    this seed can't rely on that having happened yet on a brand-new
    deployment, so it stages the same file the same way, up front."""

    path = upload_queue.UPLOAD_DIR / CATALOG_AUDIO_SUBDIR / "cuemix-demo.wav"
    if path.exists() or not _SEED_AUDIO_SOURCE.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SEED_AUDIO_SOURCE, path)


def _seed_catalog_tracks(db: Session, rng: random.Random, seeded: list[SeededUser], now: datetime) -> int:
    demo_storage = "cuemix-demo.wav"
    chosen = rng.sample(seeded, k=min(10, len(seeded)))
    count = 0
    for seeded_user in chosen:
        genre = rng.choice(seeded_user.genres)
        artist = rng.choice(content.ARTISTS_BY_GENRE[genre])
        title = f"{rng.choice(content.TRACK_TITLE_ADJECTIVES)} {rng.choice(content.TRACK_TITLE_NOUNS)}"
        created_at = min(seeded_user.joined_at + timedelta(days=rng.randint(1, 120)), now)
        db.add(
            CatalogTrack(
                owner_id=seeded_user.user.id,
                title=title,
                artist=artist,
                album=f"{artist} Sessions",
                genre=genre,
                mood_bucket=None,
                vibe_label=None,
                storage_name=demo_storage,
                content_type="audio/wav",
                duration_seconds=rng.randint(150, 260),
                analysis_status="completed",
                bpm=round(rng.uniform(85, 140), 1),
                musical_key=rng.choice(["C maj", "A min", "G maj", "E min", "D maj", "F# min"]),
                segment_start_second=0,
                segment_end_second=45,
                segment_method="whole_clip",
                created_at=created_at,
            )
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Phase 4: mixes + likes/saves
# ---------------------------------------------------------------------------


def _seed_mixes(
    db: Session, rng: random.Random, seeded: list[SeededUser], real_catalog_ids: list[int], now: datetime, counters: Counters
) -> tuple[dict[int, list[Mix]], list[tuple[SeededUser, Mix]], dict[int, list[MixSegment]]]:
    """Two passes, each flushed exactly once, rather than twice per mix
    (once for the mix's own id, once for its segments'): every Mix is built
    and added first, then a single flush assigns every mix.id at once
    (needed as a real FK value before its segments can be constructed at
    all), then every MixSegment is built the same way against those now-
    known ids, flushed once more for their own ids."""

    mix_plan: list[tuple[SeededUser, Mix, str, str]] = []
    for seeded_user in seeded:
        n_mixes = rng.choices([0, 1, 2, 3, 4], weights=[10, 30, 30, 20, 10])[0]
        for _ in range(n_mixes):
            genre = rng.choice(seeded_user.genres)
            vibe = seeded_user.vibe
            prompt_text = rng.choice(content.SESSION_PROMPT_TEMPLATES).format(
                vibe=vibe, genre=genre, mood=seeded_user.mood,
            )[:300]
            created_at = min(
                seeded_user.joined_at + timedelta(days=rng.randint(1, max(2, (now - seeded_user.joined_at).days))),
                now,
            )
            status = "published" if rng.random() < 0.75 else "draft"
            published_at = None
            if status == "published":
                published_at = min(created_at + timedelta(minutes=rng.randint(5, 120)), now)
            title = prompt_text if len(prompt_text) <= 120 else f"{genre} {vibe.title()} Mix"[:120]

            mix = Mix(
                session_id=f"mix_{uuid4().hex}", owner_id=seeded_user.user.id,
                title=title, prompt=prompt_text, description=None, cover_url=None,
                status=status, created_at=created_at, published_at=published_at,
            )
            db.add(mix)
            mix_plan.append((seeded_user, mix, genre, vibe))

    db.flush()  # assigns .id to every mix at once

    mixes_by_user: dict[int, list[Mix]] = defaultdict(list)
    published: list[tuple[SeededUser, Mix]] = []
    segments_by_mix: dict[int, list[MixSegment]] = {}
    for seeded_user, mix, genre, vibe in mix_plan:
        segments: list[MixSegment] = []
        n_segments = rng.randint(2, 4)
        for position in range(1, n_segments + 1):
            seg_genre = genre if rng.random() < 0.7 else rng.choice(seeded_user.genres)
            artist = rng.choice(content.ARTISTS_BY_GENRE[seg_genre])
            title_seg = f"{rng.choice(content.TRACK_TITLE_ADJECTIVES)} {rng.choice(content.TRACK_TITLE_NOUNS)}"
            catalog_id = rng.choice(real_catalog_ids)
            end_second = rng.randint(28, 45)
            segment = MixSegment(
                mix_id=mix.id, position=position, title=title_seg, artist=artist,
                audio_url=_demo_catalog_audio_url(catalog_id), cover_url=None,
                start_second=0, end_second=end_second,
                transition_to_next="crossfade" if position < n_segments else "end",
                source="catalog", source_track_id=str(catalog_id),
                genre=seg_genre, vibe=vibe,
            )
            db.add(segment)
            segments.append(segment)
        segments_by_mix[mix.id] = segments

        mixes_by_user[seeded_user.user.id].append(mix)
        if mix.status == "published":
            published.append((seeded_user, mix))

    db.flush()  # assigns .id to every segment at once

    for other in seeded:
        for owner, mix in published:
            if mix.owner_id == other.user.id:
                continue
            floor = max(mix.published_at, other.joined_at)
            if floor > now:
                continue
            if rng.random() < 0.12:
                db.add(MixLike(user_id=other.user.id, mix_id=mix.id, created_at=_random_activity_time(rng, floor, now)))
                _finalize_notification(
                    rng,
                    forum_service.notify(
                        db, owner.user.id, other.user.id, "mix_like",
                        f"{other.user.username} liked your mix {mix.title}.", "mix", mix.id,
                    ),
                    _random_activity_time(rng, floor, now), now, counters,
                )
            if rng.random() < 0.06:
                db.add(SavedMix(user_id=other.user.id, mix_id=mix.id, created_at=_random_activity_time(rng, floor, now)))

    return dict(mixes_by_user), published, segments_by_mix


# ---------------------------------------------------------------------------
# Phase 5: DJ sessions, feedback, learned preferences, prompt shortcuts
# ---------------------------------------------------------------------------


def _seed_sessions(
    db: Session, rng: random.Random, seeded: list[SeededUser], real_catalog_ids: list[int], now: datetime
) -> dict[int, list[DJSession]]:
    sessions_by_user: dict[int, list[DJSession]] = defaultdict(list)
    preference_rows: dict[tuple[int, str], UserPreference] = {}

    for seeded_user in seeded:
        n_sessions = rng.randint(1, 4)
        for _ in range(n_sessions):
            genre = rng.choice(seeded_user.genres)
            vibe, mood = seeded_user.vibe, seeded_user.mood
            prompt = rng.choice(content.SESSION_PROMPT_TEMPLATES).format(vibe=vibe, genre=genre, mood=mood)[:300]
            intent = _fake_intent(rng, mood, seeded_user.genres)
            catalog_id = rng.choice(real_catalog_ids)
            now_playing = _build_now_playing(rng, genre, vibe, catalog_id)
            created_at = _random_activity_time(rng, seeded_user.joined_at, now)
            status = "playing" if rng.random() < 0.2 else "stopped"
            track = now_playing["segment"]["track"]
            track_key = f"{track['source']}:{track['source_track_id']}"

            session = DJSession(
                id=f"session_{uuid4().hex}",
                user_id=seeded_user.user.id,
                prompt=prompt,
                status=status,
                vibe_label=track["vibe_label"] or "Balanced opener",
                retriever_name="catalog",
                intent_json=intent,
                original_intent_json=intent,
                now_playing_json=now_playing,
                reasoning_json={
                    "selectedMoment": f"Selected {track['title']} by {track['artist']}.",
                    "transitionPlan": "Crossfade planned for the next transition.",
                },
                played_track_keys_json=[track_key],
                played_artists_json=[track["artist"]],
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(session)
            # No flush needed: DJSession.id is a self-assigned uuid4 string,
            # not an autoincrement PK, so it's already usable below without
            # a DB round-trip (unlike Mix/ForumPost's integer ids).
            sessions_by_user[seeded_user.user.id].append(session)

            prompt_shortcuts.record_prompt(db, seeded_user.user.id, prompt, PromptIntent.model_validate(intent))

            if rng.random() < 0.6:
                for _ in range(rng.randint(1, 3)):
                    kind = rng.choice(["more_energy", "less_vocals", "smoother", "reinforce"])
                    phrase = rng.choice(content.FEEDBACK_PHRASES[kind])
                    feedback_at = min(created_at + timedelta(minutes=rng.randint(2, 40)), now)
                    db.add(
                        SessionFeedback(
                            session_id=session.id, user_id=seeded_user.user.id,
                            feedback=phrase, normalized_feedback=kind, created_at=feedback_at,
                        )
                    )
                    if kind == "reinforce":
                        preference_key = f"reinforce:{intent['energy']}:{intent['vocals']}"
                    else:
                        preference_key = kind
                    pref_key = (seeded_user.user.id, preference_key)
                    pref = preference_rows.get(pref_key)
                    if pref is None:
                        pref = UserPreference(
                            user_id=seeded_user.user.id, feedback=preference_key,
                            score=0, count=0, updated_at=feedback_at,
                        )
                        db.add(pref)
                        preference_rows[pref_key] = pref
                    pref.count += 1
                    pref.score += 1
                    pref.updated_at = feedback_at

    return dict(sessions_by_user)


# ---------------------------------------------------------------------------
# Phase 6: listening events (the raw signal Music Identity analytics compute
# from live -- see music_identity_service.build_music_identity)
# ---------------------------------------------------------------------------


def _seed_listening_events(
    db: Session,
    rng: random.Random,
    seeded: list[SeededUser],
    sessions_by_user: dict[int, list[DJSession]],
    segments_by_mix: dict[int, list[MixSegment]],
    published_mixes_by_user: dict[int, list[Mix]],
    version: str,
    now: datetime,
    counters: Counters,
) -> int:
    rows: list[dict] = []
    for seeded_user in seeded:
        activity_level = rng.choices(["light", "moderate", "heavy"], weights=[30, 45, 25])[0]
        n_events = {
            "light": rng.randint(15, 35),
            "moderate": rng.randint(35, 80),
            "heavy": rng.randint(80, 160),
        }[activity_level]
        user_sessions = sessions_by_user.get(seeded_user.user.id, [])
        user_mixes = published_mixes_by_user.get(seeded_user.user.id, [])
        if not user_sessions:
            continue  # every seeded user has >=1 session in practice; defensive only

        for _ in range(n_events):
            use_mix = bool(user_mixes) and rng.random() < 0.45
            raw_started_at = _random_activity_time(rng, seeded_user.joined_at, now)
            started_at = _bias_hour(rng, raw_started_at, seeded_user, seeded_user.joined_at, now)
            genre = rng.choice(seeded_user.genres) if rng.random() < 0.75 else rng.choice(content.GENRES)
            artist = rng.choice(content.ARTISTS_BY_GENRE[genre])
            title = f"{rng.choice(content.TRACK_TITLE_ADJECTIVES)} {rng.choice(content.TRACK_TITLE_NOUNS)}"
            duration = rng.randint(140, 260)
            completion = min(1.0, max(0.05, rng.betavariate(3, 1.3)))
            seconds = max(5, int(duration * completion))
            skipped = completion < 0.35 and rng.random() < 0.5

            mix_id = segment_id = session_id = None
            seg_start, seg_end = 0, duration
            if use_mix:
                mix = rng.choice(user_mixes)
                segments = segments_by_mix.get(mix.id) or []
                if segments:
                    segment = rng.choice(segments)
                    mix_id, segment_id = mix.id, segment.id
                    seg_start, seg_end = segment.start_second, segment.end_second
                    genre, artist, title = segment.genre or genre, segment.artist, segment.title
            if mix_id is None:
                session = rng.choice(user_sessions)
                session_id = session.id

            rows.append(
                {
                    "client_event_id": f"coldseed:{version}:{seeded_user.user.id}:{counters.listening_events}",
                    "user_id": seeded_user.user.id,
                    "session_id": session_id,
                    "mix_id": mix_id,
                    "segment_id": segment_id,
                    "source": "audius",
                    "source_track_id": f"coldseed-{uuid4().hex[:10]}",
                    "track_title": title,
                    "artist_name": artist,
                    "genre": genre,
                    "vibe": seeded_user.vibe,
                    "started_at": started_at,
                    "ended_at": min(started_at + timedelta(seconds=seconds), now),
                    "seconds_listened": seconds,
                    "track_duration_seconds": duration,
                    "segment_start_second": seg_start,
                    "segment_end_second": seg_end,
                    "completion_ratio": round(min(1.0, seconds / max(1, duration)), 4),
                    "skipped": skipped,
                    "metadata_json": None,
                    "created_at": started_at,
                }
            )
            counters.listening_events += 1

    if rows:
        db.execute(sa.insert(ListeningEvent), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Phase 7: forum posts, comments, votes, attachments
# ---------------------------------------------------------------------------


def _seed_forum(
    db: Session,
    rng: random.Random,
    seeded: list[SeededUser],
    published_mixes_by_user: dict[int, list[Mix]],
    now: datetime,
    counters: Counters,
) -> tuple[list[tuple[SeededUser, ForumPost]], list[tuple[SeededUser, ForumComment]]]:
    """Three flush points instead of one per post plus one per comment
    (this is the largest phase by row count -- posts, comments, and two
    kinds of votes -- so it's the biggest single win for keeping the whole
    seed's runtime reasonable): all posts are built and flushed together,
    then all comments against those now-known post ids are built and
    flushed together, then post-votes and comment-votes (both need only
    ids already flushed by that point) are built in a final pass."""

    all_posts: list[tuple[SeededUser, ForumPost]] = []
    for seeded_user in seeded:
        n_posts = max(0, round(rng.gauss(10, 4)))
        for _ in range(n_posts):
            kind = rng.choices(["discussion", "status", "mix_share"], weights=[35, 50, 15])[0]
            user_mixes = published_mixes_by_user.get(seeded_user.user.id) or []
            if kind == "mix_share" and not user_mixes:
                kind = rng.choice(["discussion", "status"])

            genre = rng.choice(seeded_user.genres)
            other_genres = [g for g in content.GENRES if g != genre]
            genre2 = rng.choice(other_genres) if other_genres else genre
            vibe = rng.choice(content.VIBE_PHRASES)
            visibility = "friends" if rng.random() < 0.2 else "public"
            created_at = _random_activity_time(rng, seeded_user.joined_at, now)
            is_anonymous = kind == "discussion" and rng.random() < 0.08
            mix_id = None

            if kind == "discussion":
                title_t, body_t = rng.choice(content.DISCUSSION_TOPICS)
                title = title_t.format(genre=genre, genre2=genre2, vibe=vibe)[:160]
                body = body_t.format(genre=genre, genre2=genre2, vibe=vibe)
            elif kind == "status":
                title = "Music update"
                body = rng.choice(content.STATUS_BODIES).format(genre=genre, vibe=vibe)
            else:
                mix = rng.choice(user_mixes)
                title = mix.title
                body = rng.choice(content.MIX_SHARE_CAPTIONS).format(genre=genre, vibe=vibe)
                mix_id = mix.id

            post = ForumPost(
                author_id=seeded_user.user.id, title=title, body=body,
                is_anonymous=is_anonymous, kind=kind, visibility=visibility,
                mix_id=mix_id, created_at=created_at,
            )
            db.add(post)
            all_posts.append((seeded_user, post))

    db.flush()  # assigns .id to every post at once

    all_comments: list[tuple[SeededUser, ForumComment]] = []
    for author, post in all_posts:
        n_comments = rng.choices([0, 1, 2, 3, 4, 5, 6], weights=[15, 20, 20, 15, 12, 10, 8])[0]
        for _ in range(n_comments):
            commenter = rng.choice(seeded)
            if commenter.user.id == post.author_id or commenter.joined_at > now:
                continue
            floor = max(post.created_at, commenter.joined_at)
            if floor > now:
                continue
            comment_at = _random_activity_time(rng, floor, now)
            is_anon_comment = post.kind == "discussion" and rng.random() < 0.05
            comment = ForumComment(
                post_id=post.id, author_id=commenter.user.id,
                body=rng.choice(content.COMMENT_BODIES),
                is_anonymous=is_anon_comment, created_at=comment_at,
            )
            db.add(comment)
            all_comments.append((commenter, comment))

            actor_label = "Someone" if is_anon_comment else commenter.user.username
            _finalize_notification(
                rng,
                forum_service.notify(
                    db, post.author_id, commenter.user.id, "comment",
                    f"{actor_label} commented on your post.", "post", post.id,
                ),
                comment_at, now, counters,
            )

    db.flush()  # assigns .id to every comment at once

    for commenter, comment in all_comments:
        comment_voters = rng.sample(seeded, k=min(len(seeded), rng.randint(0, 5)))
        for voter in comment_voters:
            if voter.user.id == commenter.user.id:
                continue
            value = 1 if rng.random() < 0.85 else -1
            vote_at = min(comment.created_at + timedelta(hours=rng.randint(1, 48)), now)
            db.add(ForumCommentVote(comment_id=comment.id, user_id=voter.user.id, value=value, created_at=vote_at))
            if value == 1:
                _finalize_notification(
                    rng,
                    forum_service.notify(
                        db, commenter.user.id, voter.user.id, "comment_vote",
                        f"{voter.user.username} reacted to your comment.", "comment", comment.id,
                    ),
                    vote_at, now, counters,
                )

    for author, post in all_posts:
        post_voters = rng.sample(seeded, k=min(len(seeded), rng.randint(3, 25)))
        for voter in post_voters:
            if voter.user.id == post.author_id:
                continue
            floor = max(post.created_at, voter.joined_at)
            if floor > now:
                continue
            value = 1 if rng.random() < 0.82 else -1
            vote_at = _random_activity_time(rng, floor, now)
            db.add(ForumPostVote(post_id=post.id, user_id=voter.user.id, value=value, created_at=vote_at))
            if value == 1:
                _finalize_notification(
                    rng,
                    forum_service.notify(
                        db, post.author_id, voter.user.id, "post_vote",
                        f"{voter.user.username} reacted to your post.", "post", post.id,
                    ),
                    vote_at, now, counters,
                )

    return all_posts, all_comments


def _seed_attachments(
    db: Session,
    rng: random.Random,
    all_posts: list[tuple[SeededUser, ForumPost]],
    all_comments: list[tuple[SeededUser, ForumComment]],
    counters: Counters,
) -> int:
    placeholder = _build_placeholder_png((92, 140, 214))
    sha = hashlib.sha256(placeholder).hexdigest()
    upload_queue.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    def _attach(owner_id: int, created_at: datetime, *, post_id: int | None, comment_id: int | None) -> None:
        nonlocal count
        storage_name = f"coldseed-{uuid4().hex}.png"
        (upload_queue.UPLOAD_DIR / storage_name).write_bytes(placeholder)
        attachment = Attachment(
            owner_id=owner_id, kind="image", filename="cover.png", content_type="image/png",
            storage_name=storage_name, url="pending", size_bytes=len(placeholder), sha256=sha,
            post_id=post_id, comment_id=comment_id, created_at=created_at,
        )
        db.add(attachment)
        db.flush()
        attachment.url = public_api_url(f"/uploads/{attachment.id}")
        count += 1
        counters.attachments += 1

    for author, post in all_posts:
        if rng.random() < 0.1:
            _attach(post.author_id, post.created_at, post_id=post.id, comment_id=None)
    for commenter, comment in all_comments:
        if rng.random() < 0.04:
            _attach(comment.author_id, comment.created_at, post_id=None, comment_id=comment.id)
    return count


# ---------------------------------------------------------------------------
# Phase 8: direct messages between friends
# ---------------------------------------------------------------------------


def _seed_messaging(
    db: Session, rng: random.Random, seeded: list[SeededUser], friends_of: dict[int, set[int]], now: datetime, counters: Counters
) -> int:
    by_id = {s.user.id: s for s in seeded}
    considered: set[frozenset[int]] = set()
    count = 0

    for user_id, friend_ids in friends_of.items():
        for friend_id in friend_ids:
            pair = frozenset((user_id, friend_id))
            if pair in considered:
                continue
            considered.add(pair)
            if rng.random() > 0.45:
                continue  # not every friendship has an active DM thread

            a, b = by_id[user_id], by_id[friend_id]
            cursor = max(a.joined_at, b.joined_at)
            for index in range(rng.randint(2, 12)):
                sender, recipient = (a, b) if rng.random() < 0.5 else (b, a)
                sent_at = min(cursor + timedelta(hours=rng.randint(1, 96)), now)
                cursor = sent_at
                pool = content.DM_OPENERS if index == 0 else content.DM_REPLIES
                genre = rng.choice(sender.genres)
                artist = rng.choice(content.ARTISTS_BY_GENRE[genre])
                body = rng.choice(pool).format(artist=artist, genre=genre, vibe=sender.vibe)
                read_at = None
                if sent_at < now - timedelta(hours=6) and rng.random() < 0.85:
                    read_at = min(sent_at + timedelta(minutes=rng.randint(1, 600)), now)

                db.add(
                    DirectMessage(
                        sender_id=sender.user.id, recipient_id=recipient.user.id,
                        body=body, created_at=sent_at, read_at=read_at,
                    )
                )
                count += 1
                notification = forum_service.notify(
                    db, recipient.user.id, sender.user.id, "direct_message",
                    f"New message from {sender.user.username}.", "user", sender.user.id,
                )
                if notification is not None:
                    notification.created_at = sent_at
                    notification.is_read = read_at is not None
                    counters.notifications += 1
                if sent_at >= now:
                    break

    return count


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_cold_seed(db: Session, *, version: str, random_seed: int) -> dict:
    """Runs the whole cold seed once for `version`, or returns the existing
    summary immediately if that version has already been generated (see
    ColdSeedRun). Everything is staged in `db` with no intermediate commits;
    the single db.commit() at the end covers the entire dataset plus the
    ColdSeedRun marker atomically."""

    existing = db.query(ColdSeedRun).filter_by(version=version).first()
    if existing is not None:
        return {"skipped": True, "version": version, **existing.summary_json}

    rng = random.Random(random_seed)
    now = utc_now()
    counters = Counters()

    _stage_demo_audio()
    real_catalog_ids = [
        row.id for row in db.query(CatalogTrack).filter(CatalogTrack.owner_id.is_(None)).order_by(CatalogTrack.id).all()
    ]
    if not real_catalog_ids:
        # A from-metadata (non-Alembic) database, e.g. the test suite's
        # SQLite engine, never ran the migration's data insert -- self-heal
        # the same 4 rows catalog_retriever.py's own _ensure_seed_catalog
        # would, so this seed still has real, playable catalog tracks to
        # point at.
        _ensure_seed_catalog(db)
        real_catalog_ids = [row.id for row in db.query(CatalogTrack).order_by(CatalogTrack.id).all()]

    seeded_users = _seed_users(db, rng, version, now)
    friends_of = _seed_social_graph(db, rng, seeded_users, now, counters)
    extra_catalog_tracks = _seed_catalog_tracks(db, rng, seeded_users, now)
    mixes_by_user, published_mixes, segments_by_mix = _seed_mixes(db, rng, seeded_users, real_catalog_ids, now, counters)
    published_mixes_by_user: dict[int, list[Mix]] = defaultdict(list)
    for owner, mix in published_mixes:
        published_mixes_by_user[owner.user.id].append(mix)
    sessions_by_user = _seed_sessions(db, rng, seeded_users, real_catalog_ids, now)
    listening_event_count = _seed_listening_events(
        db, rng, seeded_users, sessions_by_user, segments_by_mix, dict(published_mixes_by_user), version, now, counters
    )
    all_posts, all_comments = _seed_forum(db, rng, seeded_users, dict(published_mixes_by_user), now, counters)
    attachment_count = _seed_attachments(db, rng, all_posts, all_comments, counters)
    message_count = _seed_messaging(db, rng, seeded_users, friends_of, now, counters)

    public_count = sum(1 for s in seeded_users if s.is_public)
    summary = {
        "users": len(seeded_users),
        "public_profiles": public_count,
        "private_profiles": len(seeded_users) - public_count,
        "friendships": sum(len(v) for v in friends_of.values()) // 2,
        "catalog_tracks_added": extra_catalog_tracks,
        "mixes": sum(len(v) for v in mixes_by_user.values()),
        "published_mixes": len(published_mixes),
        "dj_sessions": sum(len(v) for v in sessions_by_user.values()),
        "listening_events": listening_event_count,
        "forum_posts": len(all_posts),
        "forum_comments": len(all_comments),
        "attachments": attachment_count,
        "direct_messages": message_count,
        "notifications": counters.notifications,
    }
    db.add(ColdSeedRun(version=version, random_seed=random_seed, summary_json=summary, created_at=now))
    db.commit()
    return {"skipped": False, "version": version, **summary}
