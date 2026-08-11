import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	envPrefix: ['VITE_', 'PUBLIC_'],
	server: {
		proxy: {
			'/api': {
				target: process.env.PUBLIC_API_PROXY_TARGET || 'http://127.0.0.1:5000',
				changeOrigin: true,
				ws: true
			}
		}
	}
});
