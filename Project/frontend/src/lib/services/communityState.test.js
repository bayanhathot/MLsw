import { describe, expect, it } from 'vitest';

import { reconcileById, reconcileConversationMessage } from './communityState.js';

describe('community live/HTTP state reconciliation', () => {
	it('upserts a post at the front without duplicating its live-event copy', () => {
		const live = { id: 7, body: 'live copy' };
		const response = { id: 7, body: 'authoritative response' };
		const result = reconcileById([live, { id: 6, body: 'older' }], response, 'start');

		expect(result.inserted).toBe(false);
		expect(result.items).toEqual([response, { id: 6, body: 'older' }]);
	});

	it('replaces a live comment with its response without incrementing it twice', () => {
		const live = { id: 9, body: 'comment', canDelete: false };
		const response = { id: 9, body: 'comment', canDelete: true };
		const result = reconcileById([live], response);

		expect(result.inserted).toBe(false);
		expect(result.items).toEqual([response]);
	});

	it('attributes a sent live DM to the recipient instead of creating a self conversation', () => {
		const incoming = {
			id: 11,
			sender_id: 1,
			sender_username: 'alice',
			recipient_id: 2,
			recipient_username: 'bob',
			body: 'hello',
			attachments: [],
			created_at: '2026-08-29T00:00:00Z',
			read_at: null
		};
		const result = reconcileConversationMessage([], [], incoming, 'alice', 'bob');

		expect(result.conversations[0].username).toBe('bob');
		expect(result.conversations.some((item) => item.username === 'alice')).toBe(false);
		expect(result.messages).toEqual([incoming]);
		expect(result.conversations[0].unreadCount).toBe(0);
	});

	it('updates the active incoming thread without adding an unread badge', () => {
		const incoming = {
			id: 12,
			sender_id: 2,
			sender_username: 'bob',
			recipient_id: 1,
			recipient_username: 'alice',
			body: 'reply',
			attachments: [],
			created_at: '2026-08-29T00:01:00Z',
			read_at: null
		};
		const result = reconcileConversationMessage(
			[
				{
					username: 'bob',
					displayName: 'Bobby',
					avatarUrl: null,
					lastMessage: '',
					lastMessageAt: '',
					unreadCount: 2
				}
			],
			[],
			incoming,
			'alice',
			'bob'
		);

		expect(result.messages).toEqual([incoming]);
		expect(result.conversations[0]).toMatchObject({
			username: 'bob',
			displayName: 'Bobby',
			lastMessage: 'reply',
			unreadCount: 0
		});
	});
});
