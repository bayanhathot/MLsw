# Security policy

Report vulnerabilities privately to the project maintainers; do not open a
public issue containing an exploit or secret.

CI blocks moderate, high, and critical npm advisories (`npm audit
--audit-level=moderate`); low-severity advisories are allowed to pass. As of
this writing the only outstanding low-severity finding is a `cookie <0.7.0`
advisory inherited by SvelteKit, for which npm offers no compatible patched
SvelteKit release yet (its `--force` proposal incorrectly downgrades
SvelteKit). Cuemix uses the static adapter, so this package is build-time
tooling and is absent from the final unprivileged Nginx image. Run `npm audit`
in `frontend/` for the current result; this exception should be removed once
a compatible SvelteKit release depends on `cookie >=0.7.0`.

Never commit credentials. Rotate any exposed database password, JWT secret,
SSH key, registry token, or API credential immediately.

## Third-party compliance gates

Some features are architecturally ready but blocked on an explicit answer
from whoever owns Cuemix's legal/contractual relationships, not a technical
decision. Track them here so the gate survives past a chat conversation.

### Resolved — persistent Audius analysis cache (proposed 2026-08-19, risk accepted 2026-08-20)

The "Persistent Analysis for Audius Tracks" feature (temporarily fetch an
Audius track's full audio once, run it through the same DSP pipeline used
for local uploads, persist only the derived metadata — BPM/key/Camelot/
LUFS/beat grid/phrase boundaries — and delete the temporary audio) required
an answer, from whoever owns Cuemix's legal/contractual relationships, on:

1. Temporary retrieval of full audio for analysis purposes.
2. Retention window for that temporary audio before deletion (the proposal
   assumes "delete immediately after the analysis job completes or fails").
3. Indefinite retention of *derived* metadata/analysis computed from that
   audio, even after the source audio itself is deleted.
4. Any attribution/usage requirements once Cuemix stores its own derived
   intelligence about a provider track long-term.

**Status: risk accepted, 2026-08-20, by the project owner.** Verbatim
risk-acceptance statement:

> Audius compliance gate — risk accepted.
> The project owner has reviewed the current Audius Terms of Use and Open
> Music License and accepts the remaining contractual uncertainty around
> transient server-side stream analysis and derived-metadata retention.
> CueMix is authorized to proceed with production Audius analysis using
> only API-authorized tracks and streams. Raw audio must remain temporary
> and be deleted after analysis; permanent storage is limited to derived
> analysis metadata and required provider/license/attribution information.
> This is an internal risk-acceptance decision and does not represent
> written individualized approval from Audius.

This is an internal risk-acceptance decision, not written individualized
approval from Audius. Live dispatch is authorized subject to the
constraints stated above, which the implementation must enforce, not just
intend — verified against the code on 2026-08-20:

- Only API-authorized Audius tracks/streams may be fetched: confirmed —
  `audius_service.py` only calls the public Discovery API's documented
  `/tracks/search` and `/tracks/{id}/stream` endpoints; no alternate fetch
  path exists.
- Raw audio is temporary: confirmed — `analyze_external_track()`
  (`audio_analysis.py`) deletes the temp file in a `finally` block on every
  exit path (success, analysis exception, and no-temp-file-created on
  download failure).
- Permanent storage is limited to derived analysis metadata plus
  provider/attribution fields: confirmed for "no raw audio persisted" —
  `ExternalTrack` (`database/models/external_track.py`) stores only
  provider identity, display metadata, a one-way SHA-256 integrity
  fingerprint (not audio-reconstructable), and DSP-derived analysis
  fields.

### Resolved — public mix sharing for provider-sourced (Audius) mixes (2026-08-30)

Every user-created mix — generated or Studio, catalog-only or containing
Audius/API/provider tracks — can now be published, appear in Discover, on
the creator's public profile, and be shared as a Community `mix_share`
post. This closes the attribution gap the previous entry flagged, and
resolves an inconsistency where Studio outright rejected publishing any
provider-sourced draft while a regular generated mix could publish one
anyway (via a temporary rendered file the render-cleanup sweep would later
delete out from under it).

**Design: two publication modes, chosen automatically per mix**
(`backend/app/services/publish_service.py`, the single implementation both
`routers/mixes.py` and `studio_service.py` defer to):

- `rendered_asset` — every segment is creator-owned or otherwise
  CueMix-hosted (local catalog uploads, the bundled demo tracks). CueMix
  already has the right to host this audio, so publishing promotes the
  existing rendered composite file into a durable subdirectory
  (`pipeline/audio_renderer.py`'s `promote_render_to_published`) that the
  temporary-render TTL sweep never scans, and the client plays it as a
  normal file, unchanged from before.

- `provider_manifest` — at least one segment is provider-sourced. **CueMix
  never permanently republishes a rendered derivative containing
  provider-sourced audio.** Publishing this kind of mix stores an immutable
  JSON *playback recipe* instead (ordered segments, exact millisecond
  bounds, transitions, and provider identity/attribution/rights-status
  fields) and never sets a permanent public audio URL for it. The temporary
  composite WAV a Studio render produces for in-app preview is discarded at
  publish time, never promoted, and remains subject to the existing TTL
  cleanup like any other draft render.

**Playback resolution and SSRF controls.** The public
`GET /mixes/{id}/playback-manifest` endpoint (and every internal manifest
resolver) never trusts a stored or client-supplied URL for provider audio.
Each provider segment's stream URL is rebuilt server-side, on every
request, from nothing but its own `(source, source_track_id)` identity,
through `audius_service.audius_stream_url` — the same deterministic-
URL-from-ID pattern `studio_service.resolve_track` already used for saving
a segment in the first place. `source` must be a member of an explicit
allowlist (`publish_service.ALLOWED_PROVIDERS = {"audius"}`); an unknown or
unallowlisted value is reported as an unavailable segment, never fetched.
No endpoint anywhere in this feature accepts or proxies an arbitrary URL.

**Attribution.** Each provider segment's manifest entry carries
`attribution` (a plain "Title by Artist — via Audius" string),
`provider_url` (a link back to the original track's Audius page, built
from a `permalink` now captured at search time — falls back to the Audius
homepage if a permalink was never captured for an older cached track), and
`rights_status` (`"provider_streaming"` for a provider segment,
`"creator_owned"` for a hosted one). The Studio UI, Discover/Community/
profile mix cards, and the mix player all surface this via a
"Provider-backed — via Audius" badge, attribution text, and an "Open
original track" link — **this is the attribution UI the previous entry's
gap flagged as missing.**

**Remaining licensing assumption, carried over unchanged from the entry
above:** no per-track `license` field exists in Audius's public API
response, so `license` is always `None`/absent in a manifest rather than a
guessed value — the client renders no license claim at all for a provider
segment (attribution and a link to the original are shown regardless).
This is the same "no license field available" reality already accepted
above; it applies identically to provider-manifest publishing.

**Backward compatibility.** A migration
(`alembic/versions/646dfa7ecf85_add_mix_publication_mode.py`) backfills
`publication_mode` for every already-published mix from its own segments'
`source` column (not from any hardcoded assumption), so an old
provider-sourced generated mix that predates this feature is correctly
classified `provider_manifest` retroactively. Such a row has no stored
`published_manifest_json` (that column did not exist yet); the playback
endpoint reconstructs an equivalent manifest on demand from the older
`published_segments_json` snapshot instead of ever depending on the
long-since-expired temporary render it used to point at.
