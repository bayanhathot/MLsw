import { describe, expect, it } from 'vitest';

import {
	clampWaveformMs,
	msToWaveformPosition,
	normalizeWaveformRange,
	waveformPositionToMs
} from './waveform.js';

describe('waveform range adapter', () => {
	it('converts milliseconds and normalized positions without losing ms precision', () => {
		expect(msToWaveformPosition(30_875, 123_500)).toBe(0.25);
		expect(waveformPositionToMs(0.25, 123_500)).toBe(30_875);
		expect(clampWaveformMs(130_000, 123_500)).toBe(123_500);
	});

	it('clamps a dragged start while preserving the end handle', () => {
		expect(normalizeWaveformRange(9_700, 10_000, 60_000, 1_000, 30_000, 'start')).toEqual({
			startMs: 9_000,
			endMs: 10_000
		});
	});

	it('clamps a dragged end to minimum and maximum durations', () => {
		expect(normalizeWaveformRange(5_000, 5_100, 60_000, 1_000, 10_000, 'end')).toEqual({
			startMs: 5_000,
			endMs: 6_000
		});
		expect(normalizeWaveformRange(5_000, 40_000, 60_000, 1_000, 10_000, 'end')).toEqual({
			startMs: 5_000,
			endMs: 15_000
		});
	});

	it('normalizes reversed numeric input into one valid canonical range', () => {
		expect(normalizeWaveformRange(20_000, 10_000, 60_000, 1_000, 30_000)).toEqual({
			startMs: 10_000,
			endMs: 20_000
		});
	});
});
