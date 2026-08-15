import { describe, expect, it } from 'vitest';

import { normalizePost } from './forumApi.js';
import { normalizeMessage, normalizeNotification } from './messagingApi.js';
import { normalizeMix } from './mixApi.js';
import { normalizeSession } from './sessionApi.js';
import { normalizeUploadedAttachment } from './uploadApi.js';

describe('backend response adapters', () => {
	it('normalizes a snake_case segment session into the player contract', () => {
		const session = normalizeSession(
			{
				session_id: 'mix_1',
				prompt: 'focus',
				segments: [
					{
						position: 1,
						title: 'Focus Loop',
						artist: 'Cuemix',
						audio_url: '/static/audio/demo.mp3',
						start_second: 5,
						end_second: 25
					}
				]
			},
			'fallback'
		);

		expect(session.id).toBe('mix_1');
		expect(session.audioUrl).toBe('/api/static/audio/demo.mp3');
		expect(session.nowPlaying.title).toBe('Focus Loop');
		expect(session.segments[0]).toMatchObject({ startSecond: 5, endSecond: 25 });
	});

	it('normalizes persistent mix social and segment fields', () => {
		const mix = normalizeMix({
			id: 7,
			session_id: 'mix_7',
			title: 'Night flow',
			prompt: 'coding',
			status: 'published',
			like_count: 3,
			is_liked: true,
			segments: [{ id: 9, audio_url: '/static/audio/demo.mp3' }]
		});

		expect(mix).toMatchObject({ id: 7, sessionId: 'mix_7', likeCount: 3, isLiked: true });
		expect(mix.segments[0].audioUrl).toBe('/api/static/audio/demo.mp3');
	});

	it('normalizes anonymous forum posts without leaking an author id', () => {
		const post = normalizePost({
			id: 4,
			author_id: null,
			author_username: 'Anonymous',
			title: 'Focus advice',
			body: 'What works?',
			is_anonymous: true,
			score: 2,
			comment_count: 1,
			my_vote: 1,
			can_delete: true,
			attachments: [{ id: 8, kind: 'image', url: '/static/uploads/example.png' }],
			created_at: '2026-08-11T10:00:00Z'
		});

		expect(post).toMatchObject({
			authorId: null,
			isAnonymous: true,
			canDelete: true,
			score: 2,
			myVote: 1
		});
		expect(post.attachments[0].url).toBe('/api/static/uploads/example.png');
	});

	it('normalizes media URLs in message history and live DM notification payloads', () => {
		const message = normalizeMessage({
			id: 12,
			sender_id: 1,
			sender_username: 'alice',
			recipient_id: 2,
			recipient_username: 'bob',
			attachments: [{ id: 3, kind: 'audio', url: '/api/attachments/3' }]
		});
		const notification = normalizeNotification({
			id: 4,
			kind: 'direct_message',
			direct_message: {
				...message,
				attachments: [{ id: 5, kind: 'video', url: '/static/uploads/movie.webm' }]
			}
		});

		expect(message.attachments[0].url).toBe('/api/attachments/3');
		expect(notification.direct_message?.attachments[0].url).toBe('/api/static/uploads/movie.webm');
	});

	it('normalizes attachment URLs returned by completed upload jobs', () => {
		expect(
			normalizeUploadedAttachment({ id: 7, url: '/static/uploads/result.webp' })
		).toMatchObject({
			id: 7,
			url: '/api/static/uploads/result.webp'
		});
	});
});
