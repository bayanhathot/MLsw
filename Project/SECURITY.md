# Security policy

Report vulnerabilities privately to the project maintainers; do not open a
public issue containing an exploit or secret.

CI blocks moderate, high, and critical npm advisories (`npm audit
--audit-level=moderate`); low-severity advisories are allowed to pass. As of
this writing the only outstanding low-severity finding is a `cookie <0.7.0`
advisory inherited by SvelteKit, for which npm offers no compatible patched
SvelteKit release yet (its `--force` proposal incorrectly downgrades
SvelteKit). Zonix uses the static adapter, so this package is build-time
tooling and is absent from the final unprivileged Nginx image. Run `npm audit`
in `frontend/` for the current result; this exception should be removed once
a compatible SvelteKit release depends on `cookie >=0.7.0`.

Never commit credentials. Rotate any exposed database password, JWT secret,
SSH key, registry token, or API credential immediately.
