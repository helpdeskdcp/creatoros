# Roadmap

Ordered roughly by value-per-effort for the *next* engineer picking this up.
See `docs/FINAL_AUDIT.md` for what's already done and verified.

## Near-term (would meaningfully improve what exists)

- **AI result caching** (spec item: cache identical transcript/topic/
  metadata inputs). Currently every `generate_structured()` call hits the
  configured provider fresh — real cost/latency win for repeat inputs.
  Shape: a `(prompt_name, prompt_version, input_hash, model) → result`
  table, checked before calling `AIOrchestrator`.
- **Prompt versioning**. Prompts currently live as string constants next
  to each module's `service.py`. Extracting them into a
  `prompt_templates` table/registry with a version field would let
  `docs/FINAL_AUDIT.md`-style traceability extend to "which prompt version
  produced this hook".
- **Frontend automated tests**. `vitest` is wired into `package.json` but
  no test files exist yet. Priority: `lib/api.ts`'s refresh-on-401 logic
  and `lib/auth-context.tsx`.
- **True E2E browser tests** (Playwright/Cypress) driving the real running
  app — the development session that built this could only verify the
  full flow via direct API calls plus a Next.js production build check,
  since browser automation available at build time controls a browser on
  a different machine than the app server. A CI job with both the app and
  a headless browser on the same runner would close this gap.
- **Pagination** on list endpoints. Fine today (per-user resource counts
  are small) but will need cursor-based pagination before any endpoint
  returns thousands of rows.

## Medium-term (real features, not yet started)

- **Instagram / Facebook / X / LinkedIn distribution providers**. The
  `DistributionProvider` interface and orchestrator are ready
  (`app/modules/distribution/`); each platform needs its own OAuth app
  registered and reviewed by a human, then a `<Platform>DistributionProvider`
  implementation following `youtube_provider.py`.
- **Comment Intelligence** (classify comments, mine audience questions).
  Design note in the original spec; no code yet. Would extend
  `app/modules/analytics/` or a new `comments` module, reusing the AI
  orchestrator's structured-generation pattern.
- **Growth Simulator** (scenario planning for upload frequency/format
  mix). Not started — would be a new endpoint under `/analytics/growth/`
  producing labeled `ESTIMATE` ranges, never presented as guaranteed.
- **Image generation for thumbnail briefs**. `thumbnail_briefs.image_prompt`
  is generated today; actually calling an image-generation provider and
  storing the resulting asset is not wired up. Would need a third provider
  abstraction (`ImageProvider`) parallel to `AIProvider`.

## Longer-term / infrastructure

- **Next.js 16** once it has a stable release — closes the one remaining
  build-time-only `postcss` CVE inherited from `next`'s bundled
  dependency (see `docs/security.md`).
- **Rate limiting at the gateway** (Nginx `limit_req` or a dedicated
  gateway) ahead of a public launch.
- **Multi-node deployment** — `docker-compose.yml` is single-host by
  design; translating it to Kubernetes/Nomad/etc. is mechanical (every
  service is already configured entirely via environment variables) but
  not done.
- **Formal AI usage dashboard** (spec item: track provider/model/task/
  tokens/cost/latency/cache_hit per call). `AIOrchestrator` logs each
  attempt via structlog today; aggregating that into a queryable
  dashboard is not built.
