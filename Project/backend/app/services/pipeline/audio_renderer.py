"""Real pydub/ffmpeg crossfade rendering, replacing the old placeholder that
just wrote a 0..45s metadata row without touching any audio.

A single segment is trimmed to its real selected bounds. Two or more
segments are crossfaded into one composite file using the TransitionPlanner-
computed crossfade length, and every input segment's offset within that
composite is returned so callers (mix_service) can point each MixSegment row
at the same rendered file with the right start/end seconds.

If a track's audio genuinely can't be fetched (an unreachable remote
preview), that segment is left as an honestly-labelled pass-through/cut
instead of fabricating a crossfade that never happened.
"""

import logging
import os
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

from app.core.config import public_api_url
from app.schemas import (
    BridgeRender,
    RenderedAudio,
    SelectedSegment,
    StagedRender,
    StagedTrackRender,
    TransitionPlan,
)
from app.services import upload_queue
from app.services.pipeline.interfaces import AudioRenderer

logger = logging.getLogger(__name__)

RENDER_SUBDIR = "renders"
_MAX_REMOTE_BYTES = 15 * 1024 * 1024
_REMOTE_TIMEOUT_SECONDS = 8.0

# Unlike every other cache in this codebase (audius_service.py's search
# cache, session_candidate_pool.py's pool cache), rendered files had no
# eviction policy at all -- every render (including a prepare_next() one
# that's never actually consumed, e.g. invalidated by feedback before
# advance_session() gets to it) permanently occupies disk. Long enough that
# a slow listener, or a prepared-but-not-yet-consumed prefetch render, isn't
# deleted while it might still be needed; short enough not to grow unbounded
# on a small VM disk.
RENDERED_AUDIO_TTL_SECONDS = float(os.getenv("RENDERED_AUDIO_TTL_SECONDS", "3600"))


def _render_dir() -> Path:
    directory = upload_queue.UPLOAD_DIR / RENDER_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _download(url: str) -> tuple[bytes | None, str | None]:
    """Returns (bytes, None) on success, or (None, reason) on failure -- the
    reason is a short machine-readable string surfaced all the way up into
    the pipeline debug trace (RenderedAudio.fallback_reason), so a
    pass-through is diagnosable from the live panel instead of only from
    backend logs."""

    try:
        with httpx.Client(timeout=httpx.Timeout(_REMOTE_TIMEOUT_SECONDS), follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_REMOTE_BYTES:
                        logger.warning("AudioRenderer: remote track exceeded the download cap.")
                        return None, "download_exceeded_size_cap"
                return bytes(body), None
    except httpx.HTTPStatusError as exc:
        logger.warning("AudioRenderer could not download a remote track: %s", exc)
        return None, f"download_failed_http_{exc.response.status_code}"
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("AudioRenderer could not download a remote track: %s", exc)
        return None, f"download_failed_{type(exc).__name__}"


def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _load_clip(segment: SelectedSegment) -> tuple[AudioSegment | None, str | None]:
    """Returns (clip, None) on success, or (None, reason) on failure -- see
    _download's docstring for why the reason is threaded through rather than
    just logged."""

    track = segment.track
    try:
        if track.local_path:
            # A real filename lets pydub sniff .wav and use its pure-Python
            # path; anything else (mp3/ogg/flac) shells out to ffmpeg.
            audio = AudioSegment.from_file(track.local_path)
        else:
            data, reason = _download(track.audio_url)
            if data is None:
                return None, reason
            # A BytesIO buffer has no filename to sniff from, so pydub would
            # always shell out to ffmpeg here even for plain WAV bytes;
            # checking the signature directly avoids that for the one format
            # it can always read without ffmpeg.
            audio = AudioSegment.from_file(
                BytesIO(data), format="wav" if _looks_like_wav(data) else None
            )
    except (CouldntDecodeError, OSError, IndexError) as exc:
        logger.warning("AudioRenderer could not decode %s: %s", track.source_track_id, exc)
        return None, f"decode_failed_{type(exc).__name__}"

    start_ms = max(0, segment.start_second * 1000)
    end_ms = segment.end_second * 1000
    clip = audio[start_ms:end_ms] if end_ms > start_ms else audio[start_ms:]
    return clip, None


def _local_render_path(audio_url: str) -> Path | None:
    """Resolves a public /media/renders/<file>.wav URL (as _export()
    produces) back to its on-disk path -- mirrors
    session_manager._delete_rendered_file's identical URL -> path
    resolution (kept independent rather than imported from there, to
    avoid a session_manager <-> audio_renderer import cycle; both must
    stay in sync if RENDER_SUBDIR's URL shape ever changes). None for
    anything that isn't one of our own renders -- a pass-through
    audio_url points at an external track URL instead, never something
    this function should try to open as a local file."""

    marker = f"/{RENDER_SUBDIR}/"
    if marker not in audio_url:
        return None
    filename = audio_url.rsplit("/", 1)[-1]
    root = _render_dir()
    path = (root / filename).resolve()
    if path.parent != root.resolve():
        return None
    return path


def _local_clip(audio_url: str) -> AudioSegment | None:
    """Reloads an already-rendered file straight from disk -- no network
    call, so it can't fail the way a remote track's _load_clip can.
    render_bridge uses this to reload a reserved tail (rendered moments
    earlier by render_track_transition) rather than re-fetching the
    original track's remote audio a second time."""

    path = _local_render_path(audio_url)
    if path is None or not path.is_file():
        return None
    try:
        return AudioSegment.from_file(path)
    except (CouldntDecodeError, OSError, IndexError) as exc:
        logger.warning("AudioRenderer could not reload local render %s: %s", path, exc)
        return None


def _slice_body_and_tail(
    clip: AudioSegment, *, resume_offset_ms: int, reserved_ms: int
) -> tuple[AudioSegment, AudioSegment]:
    """Splits an already-loaded clip into (body, reserved_tail): body is
    `clip[resume_offset_ms : len(clip) - reserved_ms]`, reserved_tail is
    clip's own last `reserved_ms`. `reserved_ms` is assumed already
    clamped to the clip's own duration by the caller
    (session_manager._reserved_ms_for) -- this never re-derives or
    re-clamps it; a caller passing an oversized reserved_ms gets an empty
    body, which is a caller bug to fix there, not something to silently
    paper over here."""

    body_end_ms = max(resume_offset_ms, len(clip) - reserved_ms)
    return clip[resume_offset_ms:body_end_ms], clip[len(clip) - reserved_ms:]


def _clamped_crossfade_ms(a: AudioSegment, b: AudioSegment, crossfade_ms: int) -> int:
    """Never lets a crossfade exceed either clip's own length -- shared by
    _render_composite's whole-segment blending and render_bridge's
    reserved-window blending, so this one piece of defensive clamping
    (the actual "crossfade math" worth not reimplementing) has exactly one
    implementation. The `-1` margin matches _render_composite's existing,
    pre-this-change behavior."""

    return max(0, min(crossfade_ms, len(a) - 1, len(b) - 1))


def _sweep_stale_renders(directory: Path) -> None:
    """Opportunistic, best-effort cleanup: deletes rendered files whose mtime
    is older than RENDERED_AUDIO_TTL_SECONDS. Run on every _export() call
    rather than on a schedule, since there's no background task runner in
    this codebase to hang a periodic job off of -- the same "piggyback on
    the next real call" idiom audius_service.py's cache TTL uses. A
    filesystem error here must never break an actual render, so the whole
    sweep is best-effort."""

    try:
        cutoff = time.time() - RENDERED_AUDIO_TTL_SECONDS
        for path in directory.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def _export(audio: AudioSegment) -> str:
    # WAV export/import is pure-Python in pydub (no ffmpeg subprocess), so
    # the core crossfade path works even where ffmpeg isn't installed;
    # ffmpeg is still what makes decoding compressed uploads/streams possible.
    directory = _render_dir()
    _sweep_stale_renders(directory)
    path = directory / f"{uuid4().hex}.wav"
    audio.export(path, format="wav")
    return public_api_url(f"/media/renders/{path.name}")


class PydubAudioRenderer(AudioRenderer):
    def render(
        self, segments: list[SelectedSegment], transitions: list[TransitionPlan]
    ) -> RenderedAudio:
        if not segments:
            raise ValueError("PydubAudioRenderer requires at least one segment.")
        if len(segments) == 1:
            return self._render_single(segments[0])
        return self._render_composite(segments, transitions)

    def _render_single(self, segment: SelectedSegment) -> RenderedAudio:
        clip, reason = _load_clip(segment)
        if clip is None:
            duration = max(0, segment.end_second - segment.start_second)
            return RenderedAudio(
                audio_url=segment.track.audio_url, offsets=[(0, duration)],
                is_pass_through=True, fallback_reason=reason,
            )
        return RenderedAudio(
            audio_url=_export(clip), offsets=[(0, int(len(clip) / 1000))], is_pass_through=False
        )

    def _render_composite(
        self, segments: list[SelectedSegment], transitions: list[TransitionPlan]
    ) -> RenderedAudio:
        loaded = [_load_clip(segment) for segment in segments]
        clips = [clip for clip, _reason in loaded]
        if all(clip is None for clip in clips):
            offsets = [(0, max(0, segment.end_second - segment.start_second)) for segment in segments]
            first_reason = next((reason for _clip, reason in loaded if reason), None)
            return RenderedAudio(
                audio_url=segments[0].track.audio_url, offsets=offsets,
                is_pass_through=True, fallback_reason=first_reason,
            )

        composite: AudioSegment | None = None
        offsets: list[tuple[int, int]] = []
        for index, clip in enumerate(clips):
            if clip is None:
                # Can't safely fetch this one -- record it as a zero-width
                # gap rather than fabricate audio for it.
                cursor_second = int(len(composite) / 1000) if composite is not None else 0
                offsets.append((cursor_second, cursor_second))
                continue

            if composite is None:
                composite = clip
                offsets.append((0, int(len(clip) / 1000)))
                continue

            plan = transitions[index - 1] if index - 1 < len(transitions) else None
            crossfade_ms = 0
            if plan is not None and plan.style == "crossfade":
                crossfade_ms = _clamped_crossfade_ms(composite, clip, plan.crossfade_ms)
            start_second = int((len(composite) - crossfade_ms) / 1000)
            composite = composite.append(clip, crossfade=crossfade_ms)
            offsets.append((max(0, start_second), int(len(composite) / 1000)))

        return RenderedAudio(audio_url=_export(composite), offsets=offsets, is_pass_through=False)

    def render_track_transition(
        self, segment: SelectedSegment, *, resume_offset_ms: int, reserved_ms: int
    ) -> StagedTrackRender:
        clip, reason = _load_clip(segment)
        if clip is None:
            duration_ms = max(
                0, (segment.end_second - segment.start_second) * 1000 - resume_offset_ms
            )
            return StagedTrackRender(
                body=StagedRender(
                    audio_url=segment.track.audio_url, duration_ms=duration_ms,
                    is_pass_through=True, fallback_reason=reason,
                ),
            )

        body_clip, tail_clip = _slice_body_and_tail(
            clip, resume_offset_ms=resume_offset_ms, reserved_ms=reserved_ms
        )
        body = StagedRender(audio_url=_export(body_clip), duration_ms=len(body_clip))
        reserved_tail = None
        if reserved_ms > 0:
            reserved_tail = StagedRender(audio_url=_export(tail_clip), duration_ms=len(tail_clip))
        return StagedTrackRender(body=body, reserved_tail=reserved_tail)

    def render_bridge(
        self,
        tail: StagedRender,
        next_segment: SelectedSegment,
        *,
        crossfade_ms: int,
        reserved_ms: int,
    ) -> BridgeRender:
        tail_clip = _local_clip(tail.audio_url)
        next_clip, reason = _load_clip(next_segment)
        if tail_clip is None or next_clip is None:
            failure = StagedRender(
                audio_url=next_segment.track.audio_url,
                duration_ms=max(0, (next_segment.end_second - next_segment.start_second) * 1000),
                is_pass_through=True,
                fallback_reason=reason if next_clip is None else "reserved_tail_unavailable",
            )
            return BridgeRender(bridge=failure, next_body=failure, next_reserved_tail=None)

        # Clamped once, up front, so every downstream slice agrees on the
        # same crossfade_ms -- see this method's docstring in interfaces.py
        # for why the bridge's total length (plain_prefix + blended_overlap)
        # is always exactly len(tail_clip) regardless of this clamp: a
        # smaller crossfade_ms just grows plain_prefix by the same amount
        # it shrinks blended_overlap.
        crossfade_ms = _clamped_crossfade_ms(tail_clip, next_clip, crossfade_ms)

        plain_prefix = tail_clip[: len(tail_clip) - crossfade_ms]
        blend_source = tail_clip[len(tail_clip) - crossfade_ms :]
        # .append(other, crossfade=n) blends the LAST n ms of self with the
        # FIRST n ms of other; the result is len(self) + len(other) - n
        # long, i.e. it still contains the *rest* of next_clip un-faded.
        # Slicing to [:crossfade_ms] keeps only the blended region --
        # exporting the full append() result here would duplicate the rest
        # of next_clip a second time once next_body plays, which is
        # exactly the "audio gets played twice" failure this mechanism
        # exists to avoid.
        blended_overlap = blend_source.append(next_clip, crossfade=crossfade_ms)[:crossfade_ms]
        bridge_clip = plain_prefix + blended_overlap
        bridge = StagedRender(audio_url=_export(bridge_clip), duration_ms=len(bridge_clip))

        next_body_clip, next_tail_clip = _slice_body_and_tail(
            next_clip, resume_offset_ms=crossfade_ms, reserved_ms=reserved_ms
        )
        next_body = StagedRender(
            audio_url=_export(next_body_clip), duration_ms=len(next_body_clip)
        )
        next_reserved_tail = None
        if reserved_ms > 0:
            next_reserved_tail = StagedRender(
                audio_url=_export(next_tail_clip), duration_ms=len(next_tail_clip)
            )
        return BridgeRender(
            bridge=bridge, next_body=next_body, next_reserved_tail=next_reserved_tail,
            crossfade_ms=crossfade_ms,
        )
