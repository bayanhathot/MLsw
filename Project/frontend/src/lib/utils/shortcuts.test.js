import { describe, expect, it } from 'vitest';

import { labelFor, mergeShortcuts } from './shortcuts.js';

const presets = [
	{ label: 'deep work focus', prompt: 'Create a deep work focus mix.' },
	{ label: 'late night coding', prompt: 'Create a late night coding mix.' },
	{ label: 'gym energy', prompt: 'Create a gym energy mix.' },
	{ label: 'chill and relax', prompt: 'Create a chill relaxing flow.' },
	{ label: 'party warmup', prompt: 'Create a party warmup mix.' }
];

describe('labelFor', () => {
	it('returns the prompt unchanged when it already fits', () => {
		expect(labelFor('gym energy please')).toBe('gym energy please');
	});

	it('truncates a long prompt with an ellipsis', () => {
		const long = 'Create a deep work focus mix with clean, steady, low-distraction flow.';
		const label = labelFor(long);
		expect(label.length).toBeLessThanOrEqual(32);
		expect(label.endsWith('…')).toBe(true);
	});

	it('trims surrounding whitespace before measuring/truncating', () => {
		expect(labelFor('  gym energy  ')).toBe('gym energy');
	});
});

describe('mergeShortcuts', () => {
	it('puts personalized chips ahead of static presets', () => {
		const personalized = [{ prompt: 'my usual gym mix', count: 5 }];
		const merged = mergeShortcuts(personalized, presets);
		expect(merged[0]).toEqual({ label: 'my usual gym mix', prompt: 'my usual gym mix' });
		expect(merged.slice(1)).toEqual(presets.slice(0, 4));
	});

	it('fills remaining slots up to the limit from presets', () => {
		const personalized = [
			{ prompt: 'my usual gym mix', count: 5 },
			{ prompt: 'my usual focus mix', count: 4 }
		];
		const merged = mergeShortcuts(personalized, presets, 5);
		expect(merged).toHaveLength(5);
		expect(merged.slice(2)).toEqual(presets.slice(0, 3));
	});

	it('never exceeds the limit even with more personalized chips than slots', () => {
		const personalized = Array.from({ length: 7 }, (_, index) => ({
			prompt: `personalized ${index}`,
			count: 10 - index
		}));
		const merged = mergeShortcuts(personalized, presets, 5);
		expect(merged).toHaveLength(5);
		expect(merged.every((chip) => chip.prompt.startsWith('personalized'))).toBe(true);
	});

	it('falls back to static presets alone when there are no personalized chips (guest fallback)', () => {
		const merged = mergeShortcuts([], presets, 5);
		expect(merged).toEqual(presets.slice(0, 5));
	});

	it('preserves the backend-provided ranking order of personalized chips (never re-sorts by count itself)', () => {
		const personalized = [
			{ prompt: 'second most used', count: 4 },
			{ prompt: 'most used', count: 8 }
		];
		const merged = mergeShortcuts(personalized, presets);
		expect(merged[0].prompt).toBe('second most used');
		expect(merged[1].prompt).toBe('most used');
	});
});
