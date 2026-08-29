const HISTORY_KEY_PREFIX = 'cuemix:studio-assistant-history:v1';

export const MAX_STUDIO_ASSISTANT_MESSAGES = 12;

/** @param {number|string} userId */
export function studioAssistantHistoryKey(userId) {
	return `${HISTORY_KEY_PREFIX}:user:${String(userId)}`;
}

/**
 * Keep persisted history inside the same bounds enforced by the backend API.
 * Invalid or stale browser data is ignored rather than breaking Studio.
 *
 * @param {unknown} value
 * @returns {{role:'user'|'assistant',content:string}[]}
 */
export function sanitizeStudioAssistantMessages(value) {
	if (!Array.isArray(value)) return [];
	return value
		.flatMap((message) => {
			if (!message || typeof message !== 'object') return [];
			const row = /** @type {Record<string, unknown>} */ (message);
			if (row.role !== 'user' && row.role !== 'assistant') return [];
			if (typeof row.content !== 'string') return [];
			const content = row.content.trim().slice(0, 2000);
			if (!content) return [];
			const role = /** @type {'user'|'assistant'} */ (row.role);
			return [{ role, content }];
		})
		.slice(-MAX_STUDIO_ASSISTANT_MESSAGES);
}

/**
 * @param {{getItem:(key:string)=>string|null}|null|undefined} storage
 * @param {number|string} userId
 */
export function loadStudioAssistantHistory(storage, userId) {
	try {
		return sanitizeStudioAssistantMessages(
			JSON.parse(storage?.getItem(studioAssistantHistoryKey(userId)) || '[]')
		);
	} catch {
		return [];
	}
}

/**
 * @param {{setItem:(key:string,value:string)=>void}|null|undefined} storage
 * @param {number|string} userId
 * @param {unknown} messages
 */
export function saveStudioAssistantHistory(storage, userId, messages) {
	try {
		storage?.setItem(
			studioAssistantHistoryKey(userId),
			JSON.stringify(sanitizeStudioAssistantMessages(messages))
		);
	} catch {
		// Conversation persistence is best-effort; a blocked/full browser store
		// must never make the assistant unusable.
	}
}

/**
 * @param {{removeItem:(key:string)=>void}|null|undefined} storage
 * @param {number|string} userId
 */
export function clearStudioAssistantHistory(storage, userId) {
	try {
		storage?.removeItem(studioAssistantHistoryKey(userId));
	} catch {
		// Keep the in-memory clear action functional when storage is unavailable.
	}
}

/** @param {string} value */
function transitionLabel(value) {
	return value.replaceAll('_', ' ');
}

/**
 * Turn grounded transition metrics into an immediate, actionable assistant tip.
 * The score belongs to the transition from `item` into `nextItem`.
 *
 * @typedef {Object} StudioTipSegment
 * @property {string} title
 * @property {number|null} bpm
 * @property {string} transitionType
 * @property {number|null} compatibilityScore
 * @property {Record<string, number>|null} compatibilityFactors
 *
 * @param {StudioTipSegment} item
 * @param {StudioTipSegment|undefined} nextItem
 * @returns {{tone:'good'|'neutral'|'warning'|'critical',title:string,message:string}}
 */
export function studioSegmentTip(item, nextItem) {
	if (!nextItem) {
		return {
			tone: 'neutral',
			title: 'Final segment',
			message: 'No outgoing transition to check. Make sure this ending feels intentional.'
		};
	}

	const score = item.compatibilityScore == null ? Number.NaN : Number(item.compatibilityScore);
	if (!Number.isFinite(score)) {
		return {
			tone: 'neutral',
			title: 'Preview recommended',
			message: `There is not enough metadata to rate the transition into “${nextItem.title}”. Preview it before rendering.`
		};
	}

	const factors = item.compatibilityFactors || {};
	const rankedFactors = ['tempo', 'key', 'energy', 'phrase']
		.map((name) => ({ name, value: Number(factors[name]) }))
		.filter((factor) => Number.isFinite(factor.value))
		.sort((left, right) => left.value - right.value);
	const weakest = rankedFactors[0]?.name;

	if (score < 55) {
		if (weakest === 'tempo') {
			const bpmDetail = item.bpm && nextItem.bpm ? ` (${item.bpm} → ${nextItem.bpm} BPM)` : '';
			return {
				tone: 'critical',
				title: 'Low compatibility',
				message: `Large tempo jump${bpmDetail} into “${nextItem.title}”. Move one of these segments farther apart, or use fade in/out instead.`
			};
		}
		if (weakest === 'key') {
			return {
				tone: 'critical',
				title: 'Low compatibility',
				message: `The keys may clash with “${nextItem.title}”. Reorder these segments, or use a short fade in/out to avoid a long overlap.`
			};
		}
		if (weakest === 'phrase') {
			return {
				tone: 'critical',
				title: 'Low compatibility',
				message: `Phrase timing is weak into “${nextItem.title}”. Preview the join and try a 2–4 second crossfade.`
			};
		}
		return {
			tone: 'critical',
			title: 'Low compatibility',
			message: `The energy change into “${nextItem.title}” may feel abrupt. Move one of the segments or soften it with a fade in/out.`
		};
	}

	if (score < 75) {
		const suggestion =
			item.transitionType === 'cut'
				? 'Try a 2–4 second crossfade instead of the hard cut.'
				: `Preview the ${transitionLabel(item.transitionType)} and shorten it if the overlap sounds muddy.`;
		return {
			tone: 'warning',
			title: 'Needs attention',
			message: `The transition into “${nextItem.title}” may feel uneven. ${suggestion}`
		};
	}

	if (score < 85) {
		return {
			tone: 'good',
			title: 'Good match',
			message: `This order should flow into “${nextItem.title}”. Preview the ${transitionLabel(item.transitionType)} once before rendering.`
		};
	}

	return {
		tone: 'good',
		title: 'Strong match',
		message: `This segment is highly compatible with “${nextItem.title}”; the current order is a strong choice.`
	};
}
