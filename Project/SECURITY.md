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
  fields. **Gap:** no `license` field is captured from Audius's API
  response anywhere, and no attribution UI ("via Audius" / link back) is
  rendered in the player. Basic artist-name attribution is stored and
  shown; a per-track license/attribution surface, if required by Audius's
  terms, is not yet built. Flagged here rather than silently deployed
  past, per the risk-acceptance owner's own instruction.
