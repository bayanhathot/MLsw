/** Small, pure reconciliation helpers for HTTP responses that can race the
 * live event emitted by the same server-side write. */

/**
 * @template {{ id: number }} T
 * @param {T[]} items
 * @param {T} item
 * @param {'start'|'end'} [position]
 * @returns {{ items: T[], inserted: boolean }}
 */
export function reconcileById(items, item, position = 'end') {
	const inserted = !items.some((existing) => existing.id === item.id);
	if (position === 'start') {
		return { items: [item, ...items.filter((existing) => existing.id !== item.id)], inserted };
	}
	return {
		items: inserted
			? [...items, item]
			: items.map((existing) => (existing.id === item.id ? item : existing)),
		inserted
	};
}

/**
 * @param {import('../types.js').Conversation[]} conversations
 * @param {import('../types.js').DirectMessage[]} messages
 * @param {import('../types.js').DirectMessage} incoming
 * @param {string} currentUsername
 * @param {string} activeUsername
 */
export function reconcileConversationMessage(
	conversations,
	messages,
	incoming,
	currentUsername,
	activeUsername
) {
	const sentByCurrentUser = incoming.sender_username === currentUsername;
	const otherUsername = sentByCurrentUser ? incoming.recipient_username : incoming.sender_username;
	const isActiveConversation = otherUsername === activeUsername;
	const existing = conversations.find((item) => item.username === otherUsername);
	const receivedByCurrentUser = incoming.recipient_username === currentUsername;
	const unreadCount = isActiveConversation
		? 0
		: (existing?.unreadCount || 0) + (receivedByCurrentUser ? 1 : 0);
	const conversation = {
		username: otherUsername,
		displayName: existing?.displayName || otherUsername,
		avatarUrl: existing?.avatarUrl || null,
		lastMessage: incoming.body,
		lastMessageAt: incoming.created_at,
		unreadCount
	};

	return {
		conversations: [
			conversation,
			...conversations.filter((item) => item.username !== otherUsername)
		],
		messages:
			isActiveConversation && !messages.some((item) => item.id === incoming.id)
				? [...messages, incoming]
				: messages,
		isActiveConversation,
		otherUsername
	};
}
