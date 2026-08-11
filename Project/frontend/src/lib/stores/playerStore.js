import { writable } from 'svelte/store';

const initial = { mix: null };
const store = writable(initial);

export const playerStore = {
	subscribe: store.subscribe,
	play(mix) {
		store.set({ mix });
	},
	close() {
		store.set(initial);
	}
};
