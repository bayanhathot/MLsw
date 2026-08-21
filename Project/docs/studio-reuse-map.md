# CueMix Studio reuse map

This map records the integration boundary used by Studio. Studio is an
opt-in creator path; the existing DJ/session, upload, social, and generated
mix defaults remain unchanged.

| Need | Existing authority | Studio action |
| --- | --- | --- |
| Authentication and ownership | `routers/auth.py`, `get_current_user` | Reuse unchanged |
| Catalog identity and private-track access | `CatalogTrack`, catalog visibility rules | Reuse through a narrow Studio resolver |
| Audius identity and stream URL | `audius_service`, `ExternalTrack` cache | Reuse provider identity and canonical stream URL |
| Uploads and audio validation | catalog upload route and shared `UploadQueue` | Reuse unchanged; Studio only consumes completed tracks |
| Analysis metadata | `CatalogTrack` / `ExternalTrack` analysis columns | Read BPM, key, phrase, segment and silence state |
| Waveform playback | Studio's existing `HTMLAudioElement` | WaveSurfer renders and edits against the same media element; it does not create a second playback authority |
| Segment bounds | Studio page state plus backend `MIN_SEGMENT_MS` / `MAX_SEGMENT_MS` validation | Keep exact milliseconds canonical; numeric inputs and waveform handles update the same state and the API publishes the configured limits |
| Saved moments | No first-class object existed | Add user-owned `SavedSegment` |
| Mix persistence | `Mix` / `MixSegment` | Extend with Studio revision and snapshot fields |
| Transition planning | `DeterministicTransitionPlanner` | Reuse; add a normalized explanation adapter |
| Audio rendering | `PydubAudioRenderer`, shared `UploadQueue` workers | Reuse exact millisecond rendering; queue full mixes and reject stale revisions |
| Named modes | `AutoMixMode`, `apply_auto_mix_mode` | Reuse for saved-segment auto-mix |
| Passive signals | `ListeningEvent`, `MixLike` | Reuse plus a small Studio event table for save/replay/skip |
| Analytics | `music_identity_service` and Music Identity UI | Reuse unchanged; proposal metrics already exist |
| LLM inference and capacity | Ollama plus Redis-backed semaphore in `prompt_parser.py` | Import the existing capacity implementation into the isolated Studio AI container |
| AI authority | Existing backend services and ownership checks | AI returns structured suggestions only; backend validates them |
| Deployment | existing Compose, Caddy, GitHub Actions and Azure scripts | Add one internal-only Studio AI service/image |

A reusable WaveSurfer adapter is introduced only for visualization, seeking,
analysis overlays, and draggable bounds. No second audio player, track model,
mix model, renderer, queue, Ollama container, peak-storage API, or
browser-to-model route is introduced. Numeric controls remain the accessible
and mobile fallback when waveform decoding is unavailable.
