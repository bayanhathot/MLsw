# Security policy

Report vulnerabilities privately to the project maintainers; do not open a
public issue containing an exploit or secret.

CI blocks moderate, high, and critical npm advisories. On 2026-08-11 the
remaining audit result is a low-severity `cookie <0.7.0` advisory inherited by
SvelteKit 2.70.2. npm offers no compatible patched SvelteKit release and its
`--force` proposal incorrectly downgrades SvelteKit to 0.0.30. Zonix uses the
static adapter, so this package is build-time tooling and is absent from the
final unprivileged Nginx image. This temporary exception must be removed as
soon as a compatible SvelteKit release uses `cookie >=0.7.0`.

Never commit credentials. Rotate any exposed database password, JWT secret,
SSH key, registry token, or API credential immediately.
