# Build the React app, then serve it (and proxy /api) with Caddy.
FROM node:24-alpine AS build
WORKDIR /web
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm typecheck && pnpm build

FROM caddy:2-alpine
COPY --from=build /web/dist /srv/web
