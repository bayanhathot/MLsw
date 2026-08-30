"""Unified publication policy for every user-created mix -- generated
(`routers/mixes.py`) and Studio (`studio_service.py`) alike.

Two publication modes, chosen automatically from a mix's own segments,
never by the caller:

- `rendered_asset`: every segment is creator-owned or otherwise
  CueMix-hosted (today: local catalog uploads and the bundled demo
  tracks). CueMix already has the right to host this audio permanently, so
  publishing durably promotes the existing rendered composite file (see
  `audio_renderer.promote_render_to_published`) and the client plays it
  like any other file.

- `provider_manifest`: at least one segment is sourced from an external
  provider (Audius today; `ALLOWED_PROVIDERS` is where a second one would
  be added). CueMix has never had the right to permanently redistribute a
  rendered derivative containing provider-sourced audio -- see
  SECURITY.md's "Third-party compliance gates" section. Publishing this
  kind of mix therefore never republishes a composite WAV; it publishes an
  immutable JSON *playback recipe* instead (ordered segments, exact bounds,
  transitions, and provider identity/attribution), and the public
  playback-manifest endpoint (`routers/mixes.py`) resolves each provider
  segment's real stream URL live, from nothing but its own (source,
  source_track_id) identity -- never from a client-supplied URL, and never
  for a source outside `ALLOWED_PROVIDERS`. This is the same non-trust
  pattern `studio_service.resolve_track` already uses for saving a segment
  in the first place; this module is what applies it again, symmetrically,
  at publish and playback time.

Both `routers/mixes.py`'s generated-mix publish endpoint and
`studio_service.publish_mix` call into this module's `publish_mix` --
each keeps its own pre-existing idempotency/concurrency rules (a generated
mix's publish is a no-op once already published; a Studio draft's publish
still 409s once published, requiring `duplicate_mix` to keep editing) and
only defers the actual rights-check / mode-selection / manifest-building
work here, so there is exactly one implementation of that shared policy.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.database.models.catalog import CatalogTrack
from app.database.models.external_track import ExternalTrack
from app.database.models.mix import Mix, MixSegment
from app.services import audius_service, known_broken_tracks
from app.services.pipeline import audio_renderer

MODE_RENDERED_ASSET = "rendered_asset"
MODE_PROVIDER_MANIFEST = "provider_manifest"

# The only providers a public manifest may ever resolve playback for.
# "catalog" is deliberately not a member of this set: it is CueMix-hosted
# audio, not a third-party provider, and is resolved through the existing
# `/catalog/tracks/{id}/audio` route instead of this allowlist.
ALLOWED_PROVIDERS = {"audius"}

MANIFEST_SCHEMA_VERSION = 1

# Reasonable ceilings (requirement: "put reasonable limits on segment
# count, duration, transition length, and metadata size") -- generous
# enough that no real mix trips them (Studio already caps a draft at
# MAX_STUDIO_MIX_SEGMENTS=50 segments and an 8s transition via
# StudioTransitionUpdate), applied here too since a public manifest is
# untrusted-input-shaped even though every value in it actually came from
# this app's own database, not a request body.
MAX_PUBLISHED_SEGMENTS = 50
MAX_TRANSITION_DURATION_MS = 8000
MAX_ATTRIBUTION_TEXT_LEN = 300


def is_provider_source(source: str) -> bool:
    return source != "catalog"


def determine_publication_mode(segments: list[MixSegment]) -> str:
    if any(is_provider_source(item.source) for item in segments):
        return MODE_PROVIDER_MANIFEST
    return MODE_RENDERED_ASSET


def _segment_bounds_ms(item: MixSegment) -> tuple[int, int]:
    start_ms = item.source_start_ms if item.source_start_ms is not None else item.start_second * 1000
    end_ms = item.source_end_ms if item.source_end_ms is not None else item.end_second * 1000
    return int(start_ms), int(end_ms)


def _validate_publishable(db: Session, mix: Mix, segments: list[MixSegment]) -> None:
    if not segments:
        raise HTTPException(status_code=422, detail="Add at least one segment before publishing.")
    if len(segments) > MAX_PUBLISHED_SEGMENTS:
        raise HTTPException(
            status_code=422,
            detail=f"A mix can have at most {MAX_PUBLISHED_SEGMENTS} segments to publish.",
        )

    provider_ids: set[tuple[str, str]] = set()
    catalog_ids: set[int] = set()
    for item in segments:
        if item.source != "catalog" and item.source not in ALLOWED_PROVIDERS:
            raise HTTPException(
                status_code=422, detail=f"'{item.source}' is not an allowlisted audio source."
            )
        duration_ms = item.transition_duration_ms or 0
        if duration_ms < 0 or duration_ms > MAX_TRANSITION_DURATION_MS:
            raise HTTPException(status_code=422, detail="A transition duration is out of bounds.")
        start_ms, end_ms = _segment_bounds_ms(item)
        if start_ms < 0 or end_ms <= start_ms:
            raise HTTPException(
                status_code=422, detail="Every segment must have valid start/end bounds."
            )
        if item.source == "catalog":
            try:
                catalog_ids.add(int(item.source_track_id))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="A hosted track reference is invalid.") from None
        else:
            if not item.source_track_id:
                raise HTTPException(status_code=422, detail="A provider track reference is invalid.")
            provider_ids.add((item.source, item.source_track_id))

    # Reject only a provider segment already known, from this app's own
    # cross-session record, to be broken (see known_broken_tracks.py) --
    # deliberately NOT "does an ExternalTrack row exist for it": a regular
    # generated mix's Audius fallback segments come from
    # AudiusCandidateRetriever, which (unlike Studio's own track search)
    # never persists an ExternalTrack row at all, so requiring one here
    # would make an ordinary provider-backed generated mix unpublishable.
    # The stream URL itself is always a pure, deterministic function of
    # (source, source_track_id) -- see audius_service.audius_stream_url --
    # so there is nothing else to "resolve" before publishing; genuine
    # unavailability is what the public playback-manifest endpoint reports
    # live, per segment, without blocking publication of the rest of the
    # mix over it.
    for source, track_id in provider_ids:
        if known_broken_tracks.is_known_broken(db, f"{source}:{track_id}"):
            raise HTTPException(
                status_code=422,
                detail="A provider track in this mix is currently unavailable. Remove it and try again.",
            )

    if catalog_ids:
        rows = {
            row.id: row
            for row in db.query(CatalogTrack).filter(CatalogTrack.id.in_(catalog_ids)).all()
        }
        if len(rows) != len(catalog_ids) or any(
            not (rows[track_id].visibility == "public" or rows[track_id].owner_id == mix.owner_id)
            for track_id in catalog_ids
        ):
            raise HTTPException(
                status_code=422,
                detail="One or more hosted tracks in this mix are no longer available to publish.",
            )


def _external_track_row(db: Session, source: str, track_id: str) -> ExternalTrack | None:
    return (
        db.query(ExternalTrack)
        .filter(ExternalTrack.source == source, ExternalTrack.external_id == track_id)
        .first()
    )


def _provider_attribution(db: Session, item: MixSegment) -> dict:
    provider_url = None
    if item.source == "audius":
        row = _external_track_row(db, item.source, item.source_track_id)
        metadata = (row.provider_metadata_json or {}) if row else {}
        provider_url = audius_service.audius_track_page_url(metadata.get("permalink"))
    attribution = f"{item.title} by {item.artist} — via {item.source.capitalize()}"
    return {
        "provider_url": provider_url,
        "attribution": attribution[:MAX_ATTRIBUTION_TEXT_LEN],
        # No per-track license field is captured from any provider today
        # (see SECURITY.md's own documented gap) -- None here, not a
        # fabricated value, so the client can render "license unknown"
        # honestly rather than implying a specific license was checked.
        "license": None,
        "rights_status": "provider_streaming",
    }


def _segment_manifest_entry(db: Session, item: MixSegment) -> dict:
    start_ms, end_ms = _segment_bounds_ms(item)
    provider = is_provider_source(item.source)
    attribution = (
        _provider_attribution(db, item)
        if provider
        else {
            "provider_url": None,
            "attribution": None,
            "license": None,
            "rights_status": "creator_owned",
        }
    )
    return {
        "position": item.position,
        "title": item.title,
        "artist": item.artist,
        "cover_url": item.cover_url,
        "source": item.source,
        "source_track_id": item.source_track_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transition_type": item.transition_type,
        "transition_duration_ms": item.transition_duration_ms,
        "gain_db": None,
        # Snapshotted at publish time -- publishing already required every
        # provider segment to resolve above, so "available" is accurate as
        # of now. The public playback-manifest endpoint re-checks liveness
        # per request and reports a fresher value than this stored one;
        # this is the historical record, not the live source of truth.
        "availability": "available",
        **attribution,
    }


def build_manifest(mix: Mix, segments: list[MixSegment], db: Session) -> dict:
    ordered = sorted(segments, key=lambda item: item.position)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mix_id": mix.id,
        "revision": mix.revision,
        "mode": MODE_PROVIDER_MANIFEST,
        "title": mix.title,
        "segments": [_segment_manifest_entry(db, item) for item in ordered],
    }


def _legacy_segment_snapshot(segments: list[MixSegment]) -> list[dict]:
    """Kept alongside published_manifest_json for backward compatibility --
    this is the shape `studio_service.publish_mix` already persisted into
    `published_segments_json` before this module existed; unrelated
    consumers of that column keep working unchanged."""

    return [
        {
            "id": item.id,
            "position": item.position,
            "title": item.title,
            "artist": item.artist,
            "source": item.source,
            "source_track_id": item.source_track_id,
            "source_start_ms": item.source_start_ms,
            "source_end_ms": item.source_end_ms,
            "transition_type": item.transition_type,
            "transition_duration_ms": item.transition_duration_ms,
        }
        for item in sorted(segments, key=lambda item: item.position)
    ]


def _promote_rendered_asset(mix: Mix, segments: list[MixSegment]) -> str | None:
    candidate = mix.rendered_audio_url or (segments[0].audio_url if segments else None)
    if not candidate:
        return None
    durable = audio_renderer.promote_render_to_published(candidate)
    return durable or candidate


def publish_mix(db: Session, mix: Mix) -> Mix:
    """Shared publish policy: validates rights/bounds, picks the
    publication mode from the mix's own segments, and persists either a
    durable rendered asset or an immutable provider manifest. Callers keep
    their own draft/idempotency/concurrency checks (see this module's own
    docstring) and must call this only once those have already passed."""

    segments = sorted(mix.segments, key=lambda item: item.position)
    _validate_publishable(db, mix, segments)
    mode = determine_publication_mode(segments)

    mix.status = "published"
    mix.visibility = "public"
    mix.published_at = utc_now()
    mix.published_revision = mix.revision
    mix.publication_mode = mode
    mix.published_segments_json = _legacy_segment_snapshot(segments)

    if mode == MODE_RENDERED_ASSET:
        mix.published_audio_url = _promote_rendered_asset(mix, segments)
        mix.published_manifest_json = None
    else:
        # Never expose the temporary composite render (if one exists at
        # all -- render_mix always makes one for Studio's own preview
        # player) as the permanent public audio for a provider mix; the
        # manifest is the only permanent public artifact.
        mix.published_audio_url = None
        mix.published_manifest_json = build_manifest(mix, segments, db)

    db.commit()
    db.refresh(mix)
    return mix


@dataclass
class ResolvedManifestSegment:
    position: int
    title: str
    artist: str
    cover_url: str | None
    source: str
    source_track_id: str
    audio_url: str | None
    start_ms: int
    end_ms: int
    transition_type: str
    transition_duration_ms: int
    gain_db: float | None
    provider_url: str | None
    attribution: str | None
    license: str | None
    rights_status: str
    availability: str
    unavailable_reason: str | None


def _catalog_audio_url(track_id: int) -> str | None:
    from app.core.config import public_api_url

    return public_api_url(f"/catalog/tracks/{track_id}/audio")


def _resolve_manifest_segment(db: Session, entry: dict) -> ResolvedManifestSegment:
    source = str(entry.get("source") or "")
    source_track_id = str(entry.get("source_track_id") or "")
    audio_url: str | None = None
    availability = "available"
    unavailable_reason: str | None = None

    if source == "catalog":
        try:
            row = db.get(CatalogTrack, int(source_track_id))
        except (TypeError, ValueError):
            row = None
        if row is None:
            availability, unavailable_reason = "unavailable", "track_removed"
        else:
            audio_url = _catalog_audio_url(row.id)
    elif source in ALLOWED_PROVIDERS:
        # Rebuilt server-side from the provider's own deterministic URL
        # scheme + this segment's own stable id -- never from anything in
        # `entry` itself, which is why a stored manifest carries no URL an
        # attacker could have poisoned in the first place (see
        # _validate_publishable's own comment on why an ExternalTrack row
        # is not required to exist here).
        audio_url = audius_service.audius_stream_url(source_track_id)
        if known_broken_tracks.is_known_broken(db, f"{source}:{source_track_id}"):
            audio_url = None
            availability, unavailable_reason = "unavailable", "provider_track_broken"
    else:
        availability, unavailable_reason = "unavailable", "unknown_provider"

    return ResolvedManifestSegment(
        position=int(entry.get("position") or 0),
        title=str(entry.get("title") or ""),
        artist=str(entry.get("artist") or ""),
        cover_url=entry.get("cover_url"),
        source=source,
        source_track_id=source_track_id,
        audio_url=audio_url,
        start_ms=int(entry.get("start_ms") or 0),
        end_ms=int(entry.get("end_ms") or 0),
        transition_type=str(entry.get("transition_type") or "cut"),
        transition_duration_ms=int(entry.get("transition_duration_ms") or 0),
        gain_db=entry.get("gain_db"),
        provider_url=entry.get("provider_url"),
        attribution=entry.get("attribution"),
        license=entry.get("license"),
        rights_status=str(entry.get("rights_status") or "creator_owned"),
        availability=availability,
        unavailable_reason=unavailable_reason,
    )


def _manifest_or_fallback(mix: Mix) -> dict:
    """Every publish since this module shipped stores a real manifest; a
    mix published before that (publication_mode backfilled by migration,
    published_manifest_json left NULL -- see that migration's own
    docstring) reconstructs an equivalent one from the older
    published_segments_json snapshot instead of ever depending on the since
    -expired temporary render it used to point at."""

    if mix.published_manifest_json:
        return mix.published_manifest_json
    legacy = mix.published_segments_json or []
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mix_id": mix.id,
        "revision": mix.published_revision or mix.revision,
        "mode": MODE_PROVIDER_MANIFEST,
        "title": mix.title,
        "segments": [
            {
                "position": item.get("position"),
                "title": item.get("title"),
                "artist": item.get("artist"),
                "cover_url": None,
                "source": item.get("source"),
                "source_track_id": item.get("source_track_id"),
                "start_ms": item.get("source_start_ms") or 0,
                "end_ms": item.get("source_end_ms") or 0,
                "transition_type": item.get("transition_type") or "cut",
                "transition_duration_ms": item.get("transition_duration_ms") or 0,
                "gain_db": None,
                "provider_url": None,
                "attribution": None,
                "license": None,
                "rights_status": "provider_streaming",
                "availability": "available",
            }
            for item in legacy
        ],
    }


def get_playback_manifest(db: Session, mix: Mix) -> dict:
    """Mode-aware entry point for GET /mixes/{id}/playback-manifest --
    a rendered_asset mix's "manifest" is just its one durable audio_url
    plus its already-public segment list (no live resolution needed, it
    is not provider-sourced); a provider_manifest mix defers to
    resolve_playback_manifest for real per-segment resolution."""

    if mix.publication_mode != MODE_PROVIDER_MANIFEST:
        segments = sorted(mix.segments, key=lambda item: item.position)
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "mix_id": mix.id,
            "revision": mix.published_revision or mix.revision,
            "mode": MODE_RENDERED_ASSET,
            "title": mix.title,
            "audio_url": mix.published_audio_url,
            "segments": [
                ResolvedManifestSegment(
                    position=item.position,
                    title=item.title,
                    artist=item.artist,
                    cover_url=item.cover_url,
                    source=item.source,
                    source_track_id=item.source_track_id,
                    audio_url=mix.published_audio_url,
                    start_ms=item.start_second * 1000,
                    end_ms=item.end_second * 1000,
                    transition_type=item.transition_type,
                    transition_duration_ms=item.transition_duration_ms,
                    gain_db=None,
                    provider_url=None,
                    attribution=None,
                    license=None,
                    rights_status="creator_owned",
                    availability="available" if mix.published_audio_url else "unavailable",
                    unavailable_reason=None if mix.published_audio_url else "asset_missing",
                )
                for item in segments
            ],
        }
    return resolve_playback_manifest(db, mix)


def resolve_playback_manifest(db: Session, mix: Mix) -> dict:
    """Builds the live, publicly-servable playback manifest for a
    published provider-manifest mix: the immutable published segment list,
    with each provider segment's real, current stream URL and availability
    resolved fresh (never persisted, never trusted from client input --
    see _resolve_manifest_segment). A segment that fails to resolve is
    reported as unavailable rather than raised as an error, so one missing
    provider track never breaks the whole mix's playback."""

    manifest = _manifest_or_fallback(mix)
    resolved = [_resolve_manifest_segment(db, entry) for entry in manifest.get("segments", [])]
    resolved.sort(key=lambda item: item.position)
    return {
        "schema_version": manifest.get("schema_version", MANIFEST_SCHEMA_VERSION),
        "mix_id": mix.id,
        "revision": manifest.get("revision", mix.published_revision or mix.revision),
        "mode": MODE_PROVIDER_MANIFEST,
        "title": manifest.get("title", mix.title),
        "audio_url": None,
        "segments": resolved,
    }
