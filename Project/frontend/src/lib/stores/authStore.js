/**
 * File: src/lib/stores/authStore.js
 *
 * Purpose:
 * Central frontend auth state.
 *
 * Important:
 * The JWT is NOT stored in localStorage.
 * The backend stores it in an HTTP-only cookie.
 */

import { writable } from 'svelte/store';
import { getCurrentUser, loginUser, logoutUser, registerUser } from '../services/authApi.js';

/**
 * @typedef {Object} AuthUser
 * @property {number} id
 * @property {string} username
 * @property {string} email
 * @property {boolean} is_active
 */

/**
 * @typedef {"checking" | "guest" | "authenticated"} AuthStatus
 */

/**
 * @typedef {Object} AuthState
 * @property {AuthStatus} status
 * @property {AuthUser | null} user
 * @property {string | null} error
 */

/**
 * @typedef {Object} RegisterParams
 * @property {string} username
 * @property {string} email
 * @property {string} password
 */

/**
 * @typedef {Object} LoginParams
 * @property {string} email
 * @property {string} password
 */

/** @type {AuthState} */
const initialState = {
	status: 'checking',
	user: null,
	error: null
};

function createAuthStore() {
	const { subscribe, set, update } = writable(initialState);
	let requestVersion = 0;

	return {
		subscribe,

		async checkAuth() {
			const currentRequest = ++requestVersion;
			update((state) => ({
				...state,
				status: 'checking',
				error: null
			}));

			try {
				const user = await getCurrentUser();

				if (currentRequest !== requestVersion) {
					return;
				}

				set({
					status: 'authenticated',
					user,
					error: null
				});
			} catch (error) {
				if (currentRequest !== requestVersion) {
					return;
				}

				set({
					status: 'guest',
					user: null,
					error:
						error && typeof error === 'object' && 'status' in error && error.status === 401
							? null
							: 'Cuemix could not verify your account.'
				});
			}
		},

		/**
		 * Register a new user.
		 *
		 * This does not store a token on the frontend.
		 * After registration, the register page calls login().
		 *
		 * @param {RegisterParams} params
		 */
		async register(params) {
			update((state) => ({
				...state,
				error: null
			}));

			return registerUser(params);
		},

		/**
		 * Login user.
		 *
		 * Backend sets the HTTP-only cookie.
		 * Then frontend calls /auth/me to get the current user object.
		 *
		 * @param {LoginParams} params
		 * @returns {Promise<AuthUser>}
		 */
		async login(params) {
			const currentRequest = ++requestVersion;
			update((state) => ({
				...state,
				error: null
			}));

			await loginUser(params);

			const user = await getCurrentUser();

			if (currentRequest !== requestVersion) {
				throw new Error('A newer account request replaced this login.');
			}

			set({
				status: 'authenticated',
				user,
				error: null
			});

			return user;
		},

		async logout() {
			try {
				requestVersion += 1;
				await logoutUser();
				set({
					status: 'guest',
					user: null,
					error: null
				});
			} catch (error) {
				update((state) => ({
					...state,
					error: error instanceof Error ? error.message : 'Could not sign out.'
				}));
				throw error;
			}
		},

		/**
		 * @param {string} message
		 */
		setError(message) {
			update((state) => ({
				...state,
				error: message
			}));
		},

		clearError() {
			update((state) => ({
				...state,
				error: null
			}));
		}
	};
}

export const authStore = createAuthStore();
