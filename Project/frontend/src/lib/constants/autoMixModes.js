/** Literal, API-backed auto-mix modes promised by the project proposal. */

export const AUTO_MIX_MODES = Object.freeze([
	Object.freeze({
		value: 'workout',
		label: 'Workout',
		description: 'High energy · electronic, hip-hop, rock',
		defaultPrompt: 'high-energy workout mix'
	}),
	Object.freeze({
		value: 'relaxation',
		label: 'Relaxation',
		description: 'Low energy · ambient, lofi, classical',
		defaultPrompt: 'calm relaxation mix'
	}),
	Object.freeze({
		value: 'emotional_tarab',
		label: 'Emotional / Tarab',
		description: 'Emotional vocals · Arabic music',
		defaultPrompt: 'emotional Arabic Tarab vocals'
	}),
	Object.freeze({
		value: 'party',
		label: 'Party',
		description: 'High energy · pop, house, electronic',
		defaultPrompt: 'upbeat party mix'
	})
]);

/** @type {Set<string>} */
const MODE_VALUES = new Set(AUTO_MIX_MODES.map((mode) => mode.value));

/** @param {unknown} value @returns {value is import('../types.js').AutoMixMode} */
export function isAutoMixMode(value) {
	return typeof value === 'string' && MODE_VALUES.has(value);
}

/** @param {unknown} value */
export function autoMixModeLabel(value) {
	return AUTO_MIX_MODES.find((mode) => mode.value === value)?.label || 'Custom';
}
