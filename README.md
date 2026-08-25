# LLM Inference Serving Benchmark

Does the serving stack actually matter? This project load-tests three ways of
serving the same open-weight LLM — a naive Hugging Face `generate()` loop,
Hugging Face **TGI**, and **vLLM** — under identical conditions, and measures
what a user would actually feel: time-to-first-token, end-to-end latency, and
sustained throughput. A second experiment profiles KV-cache memory scaling and
4-bit quantization tradeoffs.

**📊 [Live results →](#)** *(link added after deploy)*

Model under test: `Qwen/Qwen2.5-7B-Instruct`.

---

## Hypothesis

> vLLM would deliver roughly **5× the throughput** of the naive HF baseline, and
> hold **p95 TTFT under 1 second** at 30 concurrent requests.

Both halves held — but the throughput margin came from a direction the
hypothesis did not anticipate. See [Findings](#findings).

---

## Headline results

Median across 3 trials per concurrency level.

| Stack | p95 TTFT @ c=30 | Req/s @ c=30 | Highest concurrency with p95 TTFT < 1s |
|---|---|---|---|
| Naive HF | 1600 ms | 0.22 | **5** (clean breach at c=10, stays over) |
| TGI | 1000 ms | 9.71 | **inconsistent** — see note below |
| vLLM | **590 ms** | **11.25** | **30** — never breached at any level tested |

### Findings

- **vLLM held the latency target.** p95 TTFT stayed under 1000 ms at every
  concurrency level tested, ending at 590 ms at c=30. The SLA half of the
  hypothesis is confirmed outright.

- **The 50× throughput ratio is real but misleading.** At c=30 vLLM completed
  ~50× the requests/sec of naive HF, far above the hypothesised ~5×. That ratio
  is mostly the *denominator collapsing*, not vLLM being uniformly 50× faster:
  naive HF processes one request at a time, so at c=30 its queue backs up faster
  than it drains and completed throughput falls **below** its own single-user
  figure (0.223/s at c=30 vs. 0.459/s at c=1 — no failures, just severe queueing).
  A ratio against a degrading denominator is not a clean speedup number. The
  meaningful result is the *shape*: TGI and vLLM scale near-linearly with
  concurrency; the naive loop flattens, then reverses.

- **TGI's SLA result is unresolved, not a pass.** Its p95 TTFT came in under
  1000 ms at c=1 and c=10 but over at c=5, c=20 and c=30 — non-monotonic, with
  the c=20/c=30 readings landing essentially *on* the 1000 ms line. With only 3
  trials per level this most likely reflects trial-to-trial variance near the
  threshold rather than a real capacity ceiling, so no single number is
  defensible for TGI. It is reported as inconsistent rather than scored.

- **Memory, not throughput, is the wall for long contexts.** The KV cache OOMs
  at 2048 tokens × 20 concurrent, and at ≥4096 tokens with ≥10 concurrent.

- **4-bit quantization cut memory 61.5%** (14.2 GB → 5.5 GB at rest) while
  *increasing* generation speed 27% (48.9 → 62.1 tok/s). ⚠️ Single trial per
  configuration — directional only, not statistically rigorous.

---

## Repository layout

```
├── analysis/
│   ├── analyze_results.py     # loads all 45 CSVs, aggregates, emits summary
│   ├── summary.json           # canonical analysis output (site data source)
│   └── summary.csv            # flat per-stack/concurrency table
├── experiment2_memory/
│   ├── kv_cache_profile.py    # context_length × concurrency memory sweep
│   ├── kv_cache_results.csv
│   ├── quantization_compare.py
│   └── quantization_results.json
├── results/                   # raw Locust output
│   ├── naive_hf/              # c{1,5,10,20,30}_trial{1,2,3}_*.csv
│   ├── tgi/
│   └── vllm/
├── serving/                   # the three server implementations
├── shared/
│   ├── locustfile.py          # shared load-test script (TTFT + TOTAL timing)
│   └── prompts/prompt_dataset.json
├── site/                      # static results website (deployed to Vercel)
│   ├── index.html             # data embedded inline at publish time
│   ├── styles.css
│   ├── app.js                 # Chart.js rendering
│   └── embed_data.py          # re-embeds analysis/summary.json into index.html
├── docs/limitations.md
├── run_sweep.sh               # drives one stack across the full sweep
└── vercel.json
```

---

## Methodology

**Load generation.** [Locust](https://locust.io) drove each stack with a shared
script (`shared/locustfile.py`), picking randomly from an 8-prompt dataset
(`max_tokens` 40–300, average 133.75) per request. Each concurrency level ran
`--users N --spawn-rate N` for a fixed `1m` window, headless, with an 8-request
warmup before each sweep. Levels: **1, 5, 10, 20, 30** × **3 trials** =
45 Locust runs across the three stacks.

**Metrics.** Two request types were recorded per call: `TTFT` (time to first
streamed byte) and `TOTAL` (full response). For each stack × concurrency, the 3
trials' per-trial median and p95 were aggregated by taking the **median across
trials** — smoothing single-run noise without discarding the tail-latency
signal. Estimated tokens/sec multiplies measured requests/sec by the dataset's
average `max_tokens`; it is an output-length proxy, **not** a token-exact count.

**Memory experiments** (`experiment2_memory/`) ran separately from the Locust
sweeps.

### Known limitations

- The formal automated warmup step was added to `run_sweep.sh` only after a vLLM
  cold-start issue surfaced mid-project. Naive HF and TGI's `c1_trial1` runs
  predate it and may carry a small residual cold-start effect. Documented rather
  than re-run — see [`docs/limitations.md`](docs/limitations.md).
- 3 trials per level is enough to smooth noise but not enough to resolve
  differences at the SLA boundary (see the TGI finding above).
- The quantization comparison is a single trial per configuration.
- Estimated tokens/sec assumes every request emits its full `max_tokens`.

---

## Reproducing

```bash
# 1. run a sweep for one stack (server must already be up)
./run_sweep.sh vllm http://localhost:8000

# 2. aggregate all 45 result CSVs into analysis/summary.json + .csv
python3 analysis/analyze_results.py

# 3. embed the fresh summary into the static site
python3 site/embed_data.py

# 4. preview locally
python3 -m http.server 8000 --directory site
```

The site is dependency-free static HTML/CSS/JS — Chart.js via CDN, no backend,
no build step. `vercel.json` points Vercel at `site/` and skips the build.
