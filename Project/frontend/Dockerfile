FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build

WORKDIR /app

COPY package*.json ./
COPY svelte.config.js vite.config.js jsconfig.json ./

RUN npm ci

COPY . .

RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0

USER root
RUN rm -rf /usr/share/nginx/html/* \
    && chown -R 101:101 /usr/share/nginx/html

COPY --chown=101:101 nginx.conf /etc/nginx/conf.d/default.conf
# nginx -t creates /tmp/nginx.pid as root. Remove it so the unprivileged
# runtime user can create its own PID file when the container starts.
RUN nginx -t && rm -f /tmp/nginx.pid
COPY --from=build --chown=101:101 /app/build /usr/share/nginx/html

USER 101:101

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
