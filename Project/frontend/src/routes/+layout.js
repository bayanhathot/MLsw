/*
  Zonix is deployed as a client-rendered SPA behind Nginx.
  Dynamic routes such as /users/[username] and social deep links are resolved at runtime.
*/
export const ssr = false;
export const prerender = false;
