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
from app.schemas import RenderedAudio, SelectedSegment, TransitionPlan
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


def _download(url: str) -> bytes | None:
    try:
        with httpx.Client(timeout=httpx.Timeout(_REMOTE_TIMEOUT_SECONDS), follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_REMOTE_BYTES:
                        logger.warning("AudioRenderer: remote track exceeded the download cap.")
                        return None
                return bytes(body)
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("AudioRenderer could not download a remote track: %s", exc)
        return None


def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _load_clip(segment: SelectedSegment) -> AudioSegment | None:
    track = segment.track
    try:
        if track.local_path:
            # A real filename lets pydub sniff .wav and use its pure-Python
            # path; anything else (mp3/ogg/flac) shells out to ffmpeg.
            audio = AudioSegment.from_file(track.local_path)
        else:
            data = _download(track.audio_url)
            if data is None:
                return None
            # A BytesIO buffer has no filename to sniff from, so pydub would
            # always shell out to ffmpeg here even for plain WAV bytes;
            # checking the signature directly avoids that for the one format
            # it can always read without ffmpeg.
            audio = AudioSegment.from_file(
                BytesIO(data), format="wav" if _looks_like_wav(data) else None
            )
    except (CouldntDecodeError, OSError, IndexError) as exc:
        logger.warning("AudioRenderer could not decode %s: %s", track.source_track_id, exc)
        return None

    start_ms = max(0, segment.start_second * 1000)
    end_ms = segment.end_second * 1000
    return audio[start_ms:end_ms] if end_ms > start_ms else audio[start_ms:]


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
        clip = _load_clip(segment)
        if clip is None:
            duration = max(0, segment.end_second - segment.start_second)
            return RenderedAudio(
                audio_url=segment.track.audio_url, offsets=[(0, duration)], is_pass_through=True
            )
        return RenderedAudio(
            audio_url=_export(clip), offsets=[(0, int(len(clip) / 1000))], is_pass_through=False
        )

    def _render_composite(
        self, segments: list[SelectedSegment], transitions: list[TransitionPlan]
    ) -> RenderedAudio:
        clips = [_load_clip(segment) for segment in segments]
        if all(clip is None for clip in clips):
            offsets = [(0, max(0, segment.end_second - segment.start_second)) for segment in segments]
            return RenderedAudio(
                audio_url=segments[0].track.audio_url, offsets=offsets, is_pass_through=True
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
                crossfade_ms = max(0, min(plan.crossfade_ms, len(composite) - 1, len(clip) - 1))
            start_second = int((len(composite) - crossfade_ms) / 1000)
            composite = composite.append(clip, crossfade=crossfade_ms)
            offsets.append((max(0, start_second), int(len(composite) / 1000)))

        return RenderedAudio(audio_url=_export(composite), offsets=offsets, is_pass_through=False)
