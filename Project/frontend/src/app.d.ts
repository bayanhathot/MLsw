/**
 * File: src/app.d.ts
 * Purpose: SvelteKit application type declarations.
 * What it does:
 * - Gives TypeScript/JSDoc-aware tooling a place to define global app-specific interfaces.
 * - The current frontend is JavaScript with JSDoc, so the interfaces are mostly empty placeholders.
 * - Later, when backend authentication is added, Locals/PageData/PageState can be extended here.
 * Why this file exists:
 * - SvelteKit creates/uses this file as the official location for app-level type customization.
 */

// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
