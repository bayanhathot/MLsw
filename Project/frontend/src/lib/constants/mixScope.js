/** Literal, API-backed mix scope: whether each track is mixed as one
 * selected segment (today's only behavior) or start to end. Independent
 * of AutoMixMode (autoMixModes.js), which is the vibe/genre selector --
 * do not conflate the two. */

export const MIX_SCOPES = Object.freeze([
	Object.freeze({
		value: 'segments',
		label: 'Segment mixing',
		description: 'One selected moment per track'
	}),
	Object.freeze({
		value: 'full_songs',
		label: 'Full songs',
		description: 'Mix entire tracks, no trimming'
	})
]);

/** The exact behavior every existing session/request/preset already gets. */
export const DEFAULT_MIX_SCOPE = 'segments';

/** @type {Set<string>} */
const SCOPE_VALUES = new Set(MIX_SCOPES.map((scope) => scope.value));

/** @param {unknown} value @returns {value is import('../types.js').MixScope} */
export function isMixScope(value) {
	return typeof value === 'string' && SCOPE_VALUES.has(value);
}

/** @param {unknown} value */
export function mixScopeLabel(value) {
	return MIX_SCOPES.find((scope) => scope.value === value)?.label || MIX_SCOPES[0].label;
}
