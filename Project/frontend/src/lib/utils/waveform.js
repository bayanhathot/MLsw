/** @param {number} value @param {number} durationMs */
export function clampWaveformMs(value, durationMs) {
	const duration = Math.max(0, Math.round(Number(durationMs) || 0));
	return Math.min(duration, Math.max(0, Math.round(Number(value) || 0)));
}

/** @param {number} value @param {number} durationMs */
export function msToWaveformPosition(value, durationMs) {
	const duration = Math.max(0, Number(durationMs) || 0);
	return duration ? clampWaveformMs(value, duration) / duration : 0;
}

/** @param {number} position @param {number} durationMs */
export function waveformPositionToMs(position, durationMs) {
	const normalized = Math.min(1, Math.max(0, Number(position) || 0));
	return Math.round(normalized * Math.max(0, Number(durationMs) || 0));
}

/**
 * Keep a Studio selection inside the track and its configured duration limits.
 * `anchor` identifies the handle the user moved; the opposite edge is kept
 * stable whenever possible.
 *
 * @param {number} startMs
 * @param {number} endMs
 * @param {number} durationMs
 * @param {number} minDurationMs
 * @param {number} maxDurationMs
 * @param {'start'|'end'|'range'} [anchor]
 */
export function normalizeWaveformRange(
	startMs,
	endMs,
	durationMs,
	minDurationMs,
	maxDurationMs,
	anchor = 'range'
) {
	const duration = Math.max(0, Math.round(Number(durationMs) || 0));
	const minimum = Math.min(duration, Math.max(1, Math.round(Number(minDurationMs) || 1)));
	const maximum = Math.min(
		duration,
		Math.max(minimum, Math.round(Number(maxDurationMs) || duration || minimum))
	);
	let start = clampWaveformMs(startMs, duration);
	let end = clampWaveformMs(endMs, duration);

	if (anchor === 'start') {
		start = Math.min(start, Math.max(0, end - minimum));
		start = Math.max(start, end - maximum);
	} else if (anchor === 'end') {
		end = Math.max(end, Math.min(duration, start + minimum));
		end = Math.min(end, Math.min(duration, start + maximum));
	} else {
		if (end < start) [start, end] = [end, start];
		if (end - start < minimum) end = Math.min(duration, start + minimum);
		if (end - start < minimum) start = Math.max(0, end - minimum);
		if (end - start > maximum) end = start + maximum;
	}

	return { startMs: start, endMs: end };
}
