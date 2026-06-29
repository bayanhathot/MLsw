/**
 * Purpose:
 * Browser entry point for the Svelte application.
 *
 * How this connects to the project:
 * Vite loads this file from index.html. It mounts App.svelte into the #app
 * element so the Smart AI DJ frontend appears in the browser.
 *
 * Engineering decision:
 * Keep this file minimal. Page structure belongs in App.svelte, and app state
 * belongs in sessionStore.js.
 */

import { mount } from "svelte";
import "./app.css";
import App from "./App.svelte";

const app = mount(App, {
  target: document.getElementById("app")
});

export default app;
