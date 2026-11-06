# Build from the repository root: docker build -f apps/api/Dockerfile .
FROM node:24-alpine
WORKDIR /app
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/core packages/core
COPY apps/api apps/api
COPY apps/web/package.json apps/web/package.json
COPY apps/web/public/packs apps/web/public/packs
COPY data-pipeline/out data-pipeline/out
RUN npm ci --workspace @lexi/api --include-workspace-root
ENV NODE_ENV=production PORT=8787
USER node
EXPOSE 8787
CMD ["npx", "tsx", "apps/api/src/server.ts"]
