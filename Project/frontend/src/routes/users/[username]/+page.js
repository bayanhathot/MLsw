/*
  This route's content (another user's profile) is only known at runtime -
  there is no fixed set of usernames to prerender at build time. The static
  adapter's fallback (index.html) serves this route client-side instead,
  consistent with the rest of the app running in SPA mode (ssr=false).
*/
export const prerender = false;
