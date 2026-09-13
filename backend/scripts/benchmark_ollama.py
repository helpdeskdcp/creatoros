"""Repeatable Ollama benchmark for CreatorOS's CPU-only VPS.

Run manually (not part of the test suite -- it takes real wall-clock time
against a real local model) whenever a model is added/removed or the host's
Ollama config changes, to decide FAST/DEEP/CODING model routing with actual
numbers instead of guessing:

    python -m scripts.benchmark_ollama
    python -m scripts.benchmark_ollama --models qwen3:1.7b,gemma2:2b
    python -m scripts.benchmark_ollama --think   # also measure think=true

Talks to Ollama's HTTP API directly (not through AIOrchestrator) since this
is an infrastructure measurement, not a CreatorOS feature call.
"""
import argparse
import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODELS = [
    "qwen3:1.7b",
    "qwen3-mini:latest",
    "gemma2:2b",
    "qwen2.5-coder:1.5b",
    "qwen2.5-coder:3b",
]

# Representative CreatorOS FAST-mode prompts -- short generation/classification
# tasks, not long-form reasoning. DEEP-mode (think=true) is measured
# separately, on one prompt, since it is far slower and only relevant for a
# minority of CreatorOS tasks.
PROMPTS = {
    "title_generation": (
        "Generate 3 short, high-CTR YouTube title ideas for a video about "
        "brewing espresso at home on a budget. Reply as a numbered list only."
    ),
    "seo_keywords": (
        "List 5 SEO keywords for a YouTube video about beginner home espresso "
        "setups. Reply as a comma-separated list only."
    ),
    "classification": (
        "Classify this video title into exactly one category: Tech, Cooking, "
        "Fitness, Finance, Gaming, or Other. Title: 'My $200 Espresso Setup "
        "vs a $2000 Machine'. Reply with only the category word."
    ),
}


@dataclass
class BenchmarkResult:
    model: str
    prompt_name: str
    think: bool
    ok: bool
    error: str | None
    total_duration_s: float | None
    load_duration_s: float | None
    prompt_eval_count: int | None
    eval_count: int | None
    eval_duration_s: float | None
    tokens_per_second: float | None
    wall_clock_s: float


async def _run_one(
    client: httpx.AsyncClient, base_url: str, model: str, prompt_name: str, prompt: str, think: bool
) -> BenchmarkResult:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": think,
    }
    start = time.perf_counter()
    try:
        resp = await client.post(f"{base_url}/api/chat", json=payload, timeout=180.0)
        wall_clock = time.perf_counter() - start
    except httpx.TransportError as exc:
        return BenchmarkResult(
            model=model, prompt_name=prompt_name, think=think, ok=False, error=str(exc),
            total_duration_s=None, load_duration_s=None, prompt_eval_count=None,
            eval_count=None, eval_duration_s=None, tokens_per_second=None,
            wall_clock_s=time.perf_counter() - start,
        )

    if resp.status_code != 200:
        return BenchmarkResult(
            model=model, prompt_name=prompt_name, think=think, ok=False,
            error=f"HTTP {resp.status_code}: {resp.text[:200]}",
            total_duration_s=None, load_duration_s=None, prompt_eval_count=None,
            eval_count=None, eval_duration_s=None, tokens_per_second=None,
            wall_clock_s=wall_clock,
        )

    body = resp.json()
    eval_count = body.get("eval_count")
    eval_duration_ns = body.get("eval_duration")
    tokens_per_second = (
        eval_count / (eval_duration_ns / 1e9)
        if eval_count and eval_duration_ns
        else None
    )
    return BenchmarkResult(
        model=model, prompt_name=prompt_name, think=think, ok=True, error=None,
        total_duration_s=(body.get("total_duration") or 0) / 1e9,
        load_duration_s=(body.get("load_duration") or 0) / 1e9,
        prompt_eval_count=body.get("prompt_eval_count"),
        eval_count=eval_count,
        eval_duration_s=(eval_duration_ns or 0) / 1e9 if eval_duration_ns else None,
        tokens_per_second=tokens_per_second,
        wall_clock_s=wall_clock,
    )


async def run_benchmark(base_url: str, models: list[str], include_think: bool) -> list[BenchmarkResult]:
    results: list[BenchmarkResult] = []
    async with httpx.AsyncClient() as client:
        for model in models:
            for prompt_name, prompt in PROMPTS.items():
                result = await _run_one(client, base_url, model, prompt_name, prompt, think=False)
                results.append(result)
                print(
                    f"[FAST ] {model:24s} {prompt_name:18s} "
                    f"{'ok' if result.ok else 'FAIL':4s} "
                    f"wall={result.wall_clock_s:6.2f}s "
                    f"tok/s={result.tokens_per_second and round(result.tokens_per_second, 1)}"
                )
            if include_think:
                # DEEP mode measured once per model (one prompt) -- it is
                # dramatically slower on CPU and only a minority of CreatorOS
                # tasks ever use it, so we don't repeat it across all prompts.
                prompt_name, prompt = next(iter(PROMPTS.items()))
                result = await _run_one(client, base_url, model, prompt_name, prompt, think=True)
                results.append(result)
                print(
                    f"[DEEP ] {model:24s} {prompt_name:18s} "
                    f"{'ok' if result.ok else 'FAIL':4s} "
                    f"wall={result.wall_clock_s:6.2f}s "
                    f"tok/s={result.tokens_per_second and round(result.tokens_per_second, 1)}"
                )
    return results


def summarize(results: list[BenchmarkResult]) -> str:
    lines = ["| model | mode | avg wall(s) | avg tok/s | failures |", "|---|---|---|---|---|"]
    by_key: dict[tuple[str, bool], list[BenchmarkResult]] = {}
    for r in results:
        by_key.setdefault((r.model, r.think), []).append(r)
    for (model, think), rs in by_key.items():
        ok_rs = [r for r in rs if r.ok]
        avg_wall = statistics.mean(r.wall_clock_s for r in ok_rs) if ok_rs else float("nan")
        toks = [r.tokens_per_second for r in ok_rs if r.tokens_per_second]
        avg_tok = statistics.mean(toks) if toks else float("nan")
        failures = len(rs) - len(ok_rs)
        lines.append(
            f"| {model} | {'DEEP' if think else 'FAST'} | {avg_wall:.2f} | {avg_tok:.1f} | {failures} |"
        )
    return "\n".join(lines)


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--think", action="store_true", help="Also benchmark think=true (DEEP mode)")
    parser.add_argument("--out", default="scripts/ollama_benchmark_results.json")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    results = await run_benchmark(args.base_url, models, include_think=args.think)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "results": [asdict(r) for r in results],
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)

    print("\n" + summarize(results))
    print(f"\nRaw results written to {args.out}")


if __name__ == "__main__":
    asyncio.run(_main())
