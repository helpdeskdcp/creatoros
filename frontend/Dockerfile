FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system creatoros && adduser --system --ingroup creatoros creatoros

COPY --from=builder /app/public ./public
COPY --from=builder --chown=creatoros:creatoros /app/.next/standalone ./
COPY --from=builder --chown=creatoros:creatoros /app/.next/static ./.next/static

USER creatoros
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
    CMD node -e "require('http').get('http://localhost:3000', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
