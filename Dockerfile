FROM node:22-slim AS web
WORKDIR /app/nuxt-app
COPY nuxt-app/package*.json ./
RUN npm ci --no-audit --no-fund
COPY nuxt-app/ ./
RUN npm run build

FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir --break-system-packages jsonschema
WORKDIR /app
COPY agent/ agent/
COPY guides/ guides/
COPY --from=web /app/nuxt-app/.output nuxt-app/.output
RUN mkdir -p out && chown -R node:node /app
USER node
ENV OAUTH_AGENT_ROOT=/app NITRO_HOST=0.0.0.0 NITRO_PORT=3000 RESEARCH_COOLDOWN_SECONDS=60
# GEMINI_API_KEY (and optionally GEMINI_MODEL) are supplied by the host as environment variables, never baked in.
WORKDIR /app/nuxt-app
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
