# AI Orchestration

## Architecture

`app/ai/orchestrator.py:AIOrchestrator` is the single entry point for every
AI call in the system. No module outside `app/ai/` constructs an
`AIProvider` or calls an LLM API directly.

```
service.py  →  AIOrchestrator.generate_structured(task, system_prompt,
                                                    user_prompt, schema)
                        │
                        ├─ tries primary provider (default: Ollama)
                        ├─ on failure/invalid JSON, retries with a
                        │  corrective message, up to max_retries
                        ├─ falls back to AI_FALLBACK_PROVIDER if primary
                        │  is exhausted
                        └─ raises AIOrchestratorError if everything fails
                           — the caller NEVER receives a fabricated result
```

Every call validates the model's JSON output against a Pydantic schema
before it reaches application code (see `_parse_and_validate`). Raw AI
output never reaches a database write — `hooks/schemas.py`,
`titles/schemas.py`, etc. all define a `_Generated*` schema the LLM's
output must satisfy.

## Providers

- **`OllamaProvider`** (`app/ai/providers/ollama.py`) — talks to a local
  Ollama server over its `/api/chat` endpoint. Default and preferred: free,
  no data leaves the host, always available for routine tasks.
- **`OpenAICompatProvider`** (`app/ai/providers/openai_compat.py`) — talks
  to OpenAI or any OpenAI-compatible chat-completions API (vLLM,
  together.ai, groq, etc. all share this wire format). Used when
  `AI_PRIMARY_PROVIDER=openai` or as `AI_FALLBACK_PROVIDER`.

Configure in `.env`:

```
AI_PRIMARY_PROVIDER=ollama
AI_FALLBACK_PROVIDER=openai        # optional
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-mini:latest             # FAST_SMALL tier
OLLAMA_CODING_MODEL=qwen2.5-coder:1.5b     # CODING tier
OLLAMA_DEEP_MODEL=qwen3:1.7b               # DEEP tier (think=true)
OLLAMA_MAX_CONCURRENT_REQUESTS=2
OLLAMA_QUEUE_WAIT_TIMEOUT_SECONDS=30
AI_CACHE_TTL_HOURS=24
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

## FAST vs. DEEP mode (`app/ai/router.py`)

The VPS this runs on is CPU-only, no GPU. `scripts/benchmark_ollama.py`
(results in `scripts/ollama_benchmark_results.json`) measured Ollama
0.20.5's `think` parameter on every installed model:

| model | mode | avg wall(s) | avg tok/s |
|---|---|---|---|
| qwen3:1.7b | FAST (think=false) | ~4.1–4.5 | ~15–23 |
| qwen3:1.7b | DEEP (think=true) | ~37–66 | ~12–13 |
| qwen3-mini:latest | FAST | ~2.4–2.8 | ~15–25 |
| qwen3-mini:latest | DEEP | ~28–45 | ~12–13 |
| gemma2:2b | FAST | ~7.3–7.6 | ~9–10 |
| qwen2.5-coder:1.5b | FAST | ~3.2–3.8 | ~18–26 |
| qwen2.5-coder:3b | FAST | ~6.3–6.8 | ~9–13 |

**DEEP mode (`think=true`) only works on the qwen3 family.** gemma2 and
qwen2.5-coder return a hard `400 "<model> does not support thinking"` from
Ollama itself when `think=true` is requested — this is not a CreatorOS
limitation, it's the model. `app/ai/router.py:resolve_ollama_model()` never
routes a DEEP request anywhere else.

`AIOrchestrator.generate_structured(..., mode=AIMode.FAST | AIMode.DEEP)`
defaults to `FAST` — every routine CreatorOS task (titles, hooks, SEO,
captions, scripts, thumbnails, distribution copy, recommendations, Shorts
metadata) passes `mode=AIMode.FAST` explicitly at its call site so this can
never silently change. **No current CreatorOS feature calls DEEP mode** —
competitor/experiment/growth analysis in this codebase is deliberately
deterministic statistics (`app/modules/competitors/service.py`,
`app/modules/experiments/statistics.py`), not AI narration, specifically to
avoid fabricated analysis. DEEP mode is implemented, tested, and available
for a future task that genuinely needs extended reasoning — it is not
wired to anything today, matching "do not use DEEP mode for every request."

## Model routing (`ModelTier`)

Three tiers, each mapped to one settings-configurable Ollama model:

- `FAST_SMALL` (default for FAST mode) → `OLLAMA_MODEL`
- `CODING` (opt-in via `tier=ModelTier.CODING`, no current caller) → `OLLAMA_CODING_MODEL`
- `DEEP` (default for DEEP mode) → `OLLAMA_DEEP_MODEL`

Model routing only applies to the Ollama provider — an OpenAI-compatible
provider always uses its own configured model; there's no CPU-tiering
concern for a hosted API.

## Bounded concurrency (`app/ai/concurrency.py`)

The host's Ollama service runs with `OLLAMA_NUM_PARALLEL=1` and
`OLLAMA_MAX_LOADED_MODELS=1` (2 vCPU, no GPU) — letting CreatorOS fire an
unbounded number of concurrent requests at it would just make every one of
them slower, not more throughput. `BoundedConcurrencyProvider` wraps the
Ollama provider with an `asyncio.Semaphore(OLLAMA_MAX_CONCURRENT_REQUESTS)`;
a request that can't get a slot within `OLLAMA_QUEUE_WAIT_TIMEOUT_SECONDS`
fails fast with `AIQueueBusyError` (`AI_QUEUE_BUSY`) instead of queuing
indefinitely. One shared provider instance per process — no new connection
or semaphore per request.

## Failure codes

`AIOrchestratorError.code` is one of:

- `AI_PROVIDER_UNAVAILABLE` — the provider (Ollama or OpenAI-compatible
  endpoint) could not be reached at all.
- `MODEL_NOT_AVAILABLE` — reached the provider, but the model isn't
  installed/loadable there, or doesn't support the requested mode.
- `AI_GENERATION_TIMEOUT` — the provider didn't respond in time.
- `AI_QUEUE_BUSY` — the local concurrency gate was saturated.
- `AI_GENERATION_FAILED` — every provider/attempt failed for another reason
  (e.g. the model never produced schema-valid JSON).

CreatorOS never crashes on any of these — they propagate as a normal
`AIOrchestratorError` for the caller/global exception handler to turn into
an HTTP error response.

## Cost control

Per the Growth OS token-optimization policy: local Ollama is the default
for every generation task (hooks, titles, scripts, SEO, thumbnail briefs,
Next Best Video creative direction, platform-specific distribution
copy). External AI is opt-in via `AI_FALLBACK_PROVIDER` or by setting
`AI_PRIMARY_PROVIDER=openai` explicitly — CreatorOS never calls an external
paid API by default.

## What AI does and does not control

AI generates **creative content and framing** (a hook's wording, a title
candidate, a script outline, SEO copy, a thumbnail concept, the narrative
around a recommendation). AI **never** computes an analytics number,
trend score, or opportunity score — those are deterministic functions over
real stored data (see `app/core/data_quality.py` and
`app/modules/trends/service.py`/`topics/service.py` for the scoring
formulas). This split is enforced by construction: the scoring modules
never import `app.ai`.

## Adding a new AI provider

1. Implement `AIProvider` (`app/ai/providers/base.py`) — `complete()` and
   `is_available()`.
2. Register it in `app/ai/orchestrator.py:build_orchestrator()`'s
   `providers` dict.
3. No other code changes — every existing `generate_structured()` call site
   picks it up automatically via `AI_PRIMARY_PROVIDER`/`AI_FALLBACK_PROVIDER`.

## Result caching (spec item #22)

`app/ai/cache.py:cached_generate()` wraps `generate_structured()` with a
database cache keyed on `(task, prompt_version, model, mode,
hash(system_prompt + user_prompt), owner_user_id)`, backed by the
`ai_generation_cache` table. Every AI-generation service (hooks, titles,
scripts, SEO, thumbnails, recommendations, distribution assets) calls this
instead of the orchestrator directly — an identical request never reaches
the AI provider twice.

- **Creator isolation**: `owner_user_id` is part of the key. One creator's
  cached result is never returned for another creator's identical prompt,
  even if the prompt text happens to be byte-for-byte identical.
- **TTL**: every entry has `expires_at` (`AI_CACHE_TTL_HOURS`, default 24h).
  A stale row is treated as a miss and overwritten, never served. The
  `purge-expired-ai-cache` Celery beat job (hourly) physically deletes
  expired rows so the table doesn't grow unbounded.
- **Versioning/invalidation**: bump the `prompt_version` argument at a call
  site when that module's prompt wording changes enough that old cached
  results should stop being reused. `app/ai/cache.py:invalidate_for_user()`
  drops one creator's cached results (optionally scoped to one task)
  on demand, before the TTL naturally expires.

Cache writes use `db.flush()`, not `commit()` — several call sites batch
multiple generations before one commit (e.g.
`recommendations.generate_next_best_videos`), and an eager commit inside
the cache helper would break that transaction's atomicity on a mid-batch
failure.

## Observability (`app/ai/metrics.py`)

Every `cached_generate()` call (hit or miss) records one `AIRequestMetric`
row: task, mode, provider, model, cache_hit, success, error_code,
latency_ms, queue_wait_ms, prompt/completion token counts. Deliberately
**never** prompt/response content or a specific user id — this is for
latency/failure-rate observability, not an audit trail (see
`app/modules/audit` for that). `GET /metrics` exposes a 60-minute rolling
summary (request count, failure rate, cache hit rate, avg/p95 latency, avg
queue wait) as Prometheus text alongside the existing DB-pool gauge.
Recording a metric can never fail the AI call it describes — write errors
are logged and swallowed.

## TurboQuant (spec item — investigated, NOT deployed)

TurboQuant is a third-party, **experimental, not-upstream-merged** 3-bit
KV-cache/weight quantization fork of Ollama
(github.com/Lucien2468/Ollama-TurboQuant-Integration), not a feature of
stock Ollama. As of the most recent available information it has not been
merged into llama.cpp, so no released Ollama version (including the 0.20.5
running on this VPS) supports it natively — using it would mean replacing
the host's working, stable `ollama serve` binary with an unofficial
pre-release fork that its own authors describe as "NOT 100% stable or
production-safe."

Decision: **do not install it.** Reasons:

1. Not officially supported by the installed Ollama version — there is
   nothing to "turn on," only a binary swap of the production service.
2. The fork's own documentation disclaims production-safety.
3. Testing it would require modifying the one Ollama installation every
   other local-AI tool on this host (CreatorOS, Codex CLI) depends on —
   an unacceptable blast radius for an unverified, unofficial build.
4. This VPS **already has Ollama's own official, stable KV-cache
   quantization enabled** (`OLLAMA_KV_CACHE_TYPE=q8_0` in
   `/etc/systemd/system/ollama.service.d/10-cpu-perf.conf`, alongside
   `OLLAMA_FLASH_ATTENTION=1`) — the legitimate, production-safe version of
   the memory-saving benefit TurboQuant advertises is already in place.

No benchmark numbers are reported for TurboQuant because it was never
installed — per the explicit instruction not to claim TurboQuant support
without compatibility testing, and not to deploy it without a clear,
measurable, low-risk benefit. If llama.cpp/Ollama officially merge 3-bit
quantization support in a future release, re-evaluate then against a
released, supported build rather than the experimental fork.
