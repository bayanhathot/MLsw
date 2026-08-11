import { writable } from 'svelte/store';

/** @typedef {{ mix: import('../types.js').Mix | null }} PlayerState */

/** @type {PlayerState} */
const initial = { mix: null };
/** @type {import('svelte/store').Writable<PlayerState>} */
const store = writable(initial);

export const playerStore = {
	subscribe: store.subscribe,
	/** @param {import('../types.js').Mix} mix */
	play(mix) {
		store.set({ mix });
	},
	close() {
		store.set(initial);
	}
};
