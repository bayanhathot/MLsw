import { describe, expect, it } from 'vitest';

import {
	clearStudioAssistantHistory,
	loadStudioAssistantHistory,
	sanitizeStudioAssistantMessages,
	saveStudioAssistantHistory,
	studioAssistantHistoryKey,
	studioSegmentTip
} from './studioAssistant.js';

function memoryStorage() {
	/** @type {Map<string, string>} */
	const values = new Map();
	return {
		/** @param {string} key */
		getItem(key) {
			return values.get(key) ?? null;
		},
		/** @param {string} key @param {string} value */
		setItem(key, value) {
			values.set(key, value);
		},
		/** @param {string} key */
		removeItem(key) {
			values.delete(key);
		}
	};
}

function segment(overrides = {}) {
	return {
		title: 'First',
		bpm: 128,
		transitionType: 'cut',
		compatibilityScore: 80,
		compatibilityFactors: { tempo: 80, key: 80, energy: 80, phrase: 80 },
		...overrides
	};
}

describe('Studio assistant conversation history', () => {
	it('persists bounded, valid messages per user', () => {
		const storage = memoryStorage();
		const messages = Array.from({ length: 14 }, (_, index) => ({
			role: index % 2 ? 'assistant' : 'user',
			content: `message ${index}`
		}));

		saveStudioAssistantHistory(storage, 7, messages);

		expect(loadStudioAssistantHistory(storage, 7)).toHaveLength(12);
		expect(loadStudioAssistantHistory(storage, 7)[0].content).toBe('message 2');
		expect(loadStudioAssistantHistory(storage, 8)).toEqual([]);
	});

	it('ignores corrupt rows and can clear a conversation', () => {
		const storage = memoryStorage();
		storage.setItem(
			studioAssistantHistoryKey(7),
			JSON.stringify([
				{ role: 'system', content: 'not allowed' },
				{ role: 'user', content: ' remembered constraint ' },
				{ role: 'assistant', content: '' }
			])
		);

		expect(loadStudioAssistantHistory(storage, 7)).toEqual([
			{ role: 'user', content: 'remembered constraint' }
		]);
		clearStudioAssistantHistory(storage, 7);
		expect(loadStudioAssistantHistory(storage, 7)).toEqual([]);
	});

	it('fails open when browser storage is unavailable', () => {
		const unavailable = {
			getItem: () => {
				throw new Error('blocked');
			},
			setItem: () => {
				throw new Error('full');
			}
		};

		expect(loadStudioAssistantHistory(unavailable, 7)).toEqual([]);
		expect(() => saveStudioAssistantHistory(unavailable, 7, [])).not.toThrow();
		expect(sanitizeStudioAssistantMessages('invalid')).toEqual([]);
	});
});

describe('Studio segment assistant tips', () => {
	it('gives specific advice for a weak tempo transition', () => {
		const tip = studioSegmentTip(
			segment({
				compatibilityScore: 35,
				compatibilityFactors: { tempo: 15, key: 80, energy: 60, phrase: 70 }
			}),
			segment({ title: 'Second', bpm: 92 })
		);

		expect(tip.tone).toBe('critical');
		expect(tip.message).toContain('128 → 92 BPM');
		expect(tip.message).toContain('Move one of these segments');
	});

	it('suggests a crossfade for a medium hard-cut transition', () => {
		const tip = studioSegmentTip(segment({ compatibilityScore: 64 }), segment({ title: 'Second' }));

		expect(tip.tone).toBe('warning');
		expect(tip.message).toContain('crossfade');
	});

	it('recognizes strong and final placements', () => {
		expect(
			studioSegmentTip(segment({ compatibilityScore: 91 }), segment({ title: 'Second' })).title
		).toBe('Strong match');
		expect(studioSegmentTip(segment(), undefined).title).toBe('Final segment');
	});
});
