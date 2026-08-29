import { describe, expect, it } from 'vitest';

import { AUTO_MIX_MODES, autoMixModeLabel, isAutoMixMode } from './autoMixModes.js';

describe('literal auto-mix modes', () => {
	it('exposes exactly the four proposal modes', () => {
		expect(AUTO_MIX_MODES.map((mode) => mode.value)).toEqual([
			'workout',
			'relaxation',
			'emotional_tarab',
			'party'
		]);
		expect(new Set(AUTO_MIX_MODES.map((mode) => mode.value)).size).toBe(4);
	});

	it('validates API values without accepting prompt aliases', () => {
		expect(isAutoMixMode('workout')).toBe(true);
		expect(isAutoMixMode('emotional_tarab')).toBe(true);
		expect(isAutoMixMode('study')).toBe(false);
		expect(isAutoMixMode('Emotional / Tarab')).toBe(false);
	});

	it('provides user-facing labels with a safe Custom fallback', () => {
		expect(autoMixModeLabel('emotional_tarab')).toBe('Emotional / Tarab');
		expect(autoMixModeLabel(null)).toBe('Custom');
	});

	it('keeps mode metadata separate from user-authored prompt text', () => {
		expect(AUTO_MIX_MODES.every((mode) => !('defaultPrompt' in mode))).toBe(true);
	});
});
