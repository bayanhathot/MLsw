/**
 * File: src/lib/utils/shortcuts.js
 * Purpose: Pure merge logic for PromptComposer's shortcut chips.
 * What it does:
 * - Turns a personalized prompt-shortcut (backend shape: { prompt, count })
 *   into a Preset-shaped chip ({ label, prompt }) PromptComposer already
 *   knows how to render and click.
 * - Merges personalized chips ahead of the static PRESETS list, filling any
 *   remaining slots up to a cap from presets.
 * Kept separate from PromptComposer.svelte so the merge/label logic is
 * testable without mounting a Svelte component (this project has no
 * component-rendering test setup -- see e2e/smoke.spec.js for that layer).
 */

const MAX_SHORTCUT_LABEL_LENGTH = 32;

/**
 * A personalized shortcut's full prompt text is its own label, truncated
 * for the chip -- clicking it still fills in the *full* prompt text, same
 * as a static preset (see PromptComposer.svelte's usePreset).
 *
 * @param {string} prompt
 */
export function labelFor(prompt) {
	const trimmed = prompt.trim();
	if (trimmed.length <= MAX_SHORTCUT_LABEL_LENGTH) {
		return trimmed;
	}
	return `${trimmed.slice(0, MAX_SHORTCUT_LABEL_LENGTH - 1).trimEnd()}…`;
}

/**
 * Merges a user's personalized prompt shortcuts ahead of the static
 * PRESETS list, filling any remaining slots up to `limit` from presets.
 * Personalized chips are already ranked by the backend (frequency then
 * recency, see services/promptShortcutsApi.js), so their relative order is
 * preserved as-is -- this only decides how many of each kind fit.
 *
 * @param {{ prompt: string, count: number }[]} personalized
 * @param {import('../types.js').Preset[]} presets
 * @param {number} [limit]
 * @returns {import('../types.js').Preset[]}
 */
export function mergeShortcuts(personalized, presets, limit = 5) {
	const personalizedChips = personalized.slice(0, limit).map((shortcut) => ({
		label: labelFor(shortcut.prompt),
		prompt: shortcut.prompt
	}));
	const remaining = Math.max(0, limit - personalizedChips.length);
	return [...personalizedChips, ...presets.slice(0, remaining)];
}
