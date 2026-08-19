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

### Open — persistent Audius analysis cache (proposed 2026-08-19)

The "Persistent Analysis for Audius Tracks" proposal (temporarily fetch an
Audius track's full audio once, run it through the same DSP pipeline used
for local uploads, persist only the derived metadata — BPM/key/Camelot/
LUFS/beat grid/phrase boundaries — and delete the temporary audio) requires
a written answer from Audius's actual API/platform terms (Terms of
Service or partner agreement, not just the public API docs) on:

1. Temporary retrieval of full audio for analysis purposes.
2. Retention window for that temporary audio before deletion (the proposal
   assumes "delete immediately after the analysis job completes or fails").
3. Indefinite retention of *derived* metadata/analysis computed from that
   audio, even after the source audio itself is deleted.
4. Any attribution/usage requirements once Cuemix stores its own derived
   intelligence about a provider track long-term.

**Status: unanswered.** Do not wire live Audius dispatch for this feature
(the step that actually fetches and analyzes real Audius audio in
production) until this section is updated with a real answer and who gave
it. Non-dispatch implementation (schema, job queue plumbing, everything
that doesn't touch real Audius traffic) may proceed in parallel.
