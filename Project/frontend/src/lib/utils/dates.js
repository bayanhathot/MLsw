/**
 * File: src/lib/utils/dates.js
 *
 * Purpose:
 * The backend stores timestamps as naive UTC (datetime.utcnow()) and
 * serializes them without a timezone suffix, e.g. "2026-07-27T08:41:39".
 * JavaScript's Date constructor treats a timezone-less ISO string as
 * LOCAL time, not UTC, which silently shifts every timestamp by the
 * viewer's UTC offset. This helper normalizes the string before parsing
 * so every "time ago"/date display in the app is correct everywhere.
 */

/**
 * @param {string} iso
 * @returns {Date}
 */
export function parseUtcDate(iso) {
	const hasTimezone = /Z$|[+-]\d\d:\d\d$/.test(iso);

	return new Date(hasTimezone ? iso : `${iso}Z`);
}

/**
 * Parses a backend UTC timestamp and formats it, or returns `fallback` when
 * the value is missing/unparseable. Centralizes the parse-then-guard pattern
 * every per-feature date label (forum posts, profile hero, music identity,
 * message timestamps) otherwise repeats individually.
 * @param {string} iso
 * @param {(date: Date) => string} format
 * @param {string} [fallback]
 * @returns {string}
 */
export function formatUtcDate(iso, format, fallback = '') {
	const date = parseUtcDate(iso);
	return Number.isNaN(date.getTime()) ? fallback : format(date);
}
