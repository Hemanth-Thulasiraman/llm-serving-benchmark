#!/usr/bin/env python3
"""
Analysis script for the LLM inference serving benchmark.

Loads the 45 Locust stats.csv files (3 stacks x 5 concurrency levels x 3 trials),
aggregates TTFT / TOTAL latency and throughput per stack/concurrency, determines
the max concurrency at which p95 TTFT stays under 1000ms, and folds in the
KV-cache memory scaling and quantization comparison results.

Output: analysis/summary.json (consumed by the results website).
"""

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
STACKS = ["naive_hf", "tgi", "vllm"]
CONCURRENCIES = [1, 5, 10, 20, 30]
TRIALS = [1, 2, 3]
TTFT_SLA_MS = 1000

STACK_LABELS = {
    "naive_hf": "Naive HF",
    "tgi": "TGI",
    "vllm": "vLLM",
}

FNAME_RE = re.compile(r"^c(\d+)_trial(\d+)_stats\.csv$")


def load_prompt_avg_max_tokens() -> float:
    prompt_path = ROOT / "shared" / "prompts" / "prompt_dataset.json"
    prompts = json.loads(prompt_path.read_text())
    return sum(p["max_tokens"] for p in prompts) / len(prompts)


def load_stats_csv(path: Path) -> dict:
    """Extract TTFT and TOTAL rows (the per-request-type rows, not Aggregated)."""
    df = pd.read_csv(path)
    df = df[df["Name"] == "/generate"]  # drop the blank-Name "Aggregated" row
    row = {}
    for req_type in ("TTFT", "TOTAL"):
        sub = df[df["Type"] == req_type]
        if sub.empty:
            continue
        r = sub.iloc[0]
        row[req_type] = {
            "median": r["Median Response Time"],
            "average": r["Average Response Time"],
            "p95": r["95%"],
            "p99": r["99%"],
            "request_count": r["Request Count"],
            "requests_per_s": r["Requests/s"],
        }
    return row


def collect_raw_rows() -> pd.DataFrame:
    """Walk results/<stack>/c{c}_trial{t}_stats.csv for the canonical 45 files."""
    records = []
    for stack in STACKS:
        stack_dir = RESULTS_DIR / stack
        for concurrency in CONCURRENCIES:
            for trial in TRIALS:
                fname = f"c{concurrency}_trial{trial}_stats.csv"
                path = stack_dir / fname
                if not path.exists():
                    print(f"WARNING: missing {path}")
                    continue
                parsed = load_stats_csv(path)
                if "TTFT" not in parsed or "TOTAL" not in parsed:
                    print(f"WARNING: {path} missing TTFT/TOTAL rows")
                    continue
                records.append(
                    {
                        "stack": stack,
                        "concurrency": concurrency,
                        "trial": trial,
                        "ttft_median": parsed["TTFT"]["median"],
                        "ttft_avg": parsed["TTFT"]["average"],
                        "ttft_p95": parsed["TTFT"]["p95"],
                        "ttft_p99": parsed["TTFT"]["p99"],
                        "total_median": parsed["TOTAL"]["median"],
                        "total_avg": parsed["TOTAL"]["average"],
                        "total_p95": parsed["TOTAL"]["p95"],
                        "total_p99": parsed["TOTAL"]["p99"],
                        "request_count": parsed["TOTAL"]["request_count"],
                        "requests_per_s": parsed["TOTAL"]["requests_per_s"],
                    }
                )
    df = pd.DataFrame.from_records(records)
    expected = len(STACKS) * len(CONCURRENCIES) * len(TRIALS)
    print(f"Loaded {len(df)} / {expected} expected stats.csv files")
    return df


def aggregate(df: pd.DataFrame, avg_max_tokens: float) -> pd.DataFrame:
    """Median and p95-across-trials of each metric, per stack per concurrency."""
    grouped = df.groupby(["stack", "concurrency"])

    agg = grouped.agg(
        ttft_median_ms=("ttft_median", "median"),
        ttft_p95_ms=("ttft_p95", "median"),  # trial-median of each trial's own p95
        total_median_ms=("total_median", "median"),
        total_p95_ms=("total_p95", "median"),
        requests_per_s=("requests_per_s", "median"),
        trial_count=("trial", "count"),
    ).reset_index()

    # Also report the p95-across-trials (of the trial-level medians) as an
    # alternate cross-trial spread metric, useful for sanity-checking variance.
    spread = grouped.agg(
        ttft_p95_across_trials=("ttft_median", lambda s: s.quantile(0.95)),
        total_p95_across_trials=("total_median", lambda s: s.quantile(0.95)),
    ).reset_index()
    agg = agg.merge(spread, on=["stack", "concurrency"])

    agg["tokens_per_s_est"] = agg["requests_per_s"] * avg_max_tokens
    agg = agg.sort_values(["stack", "concurrency"]).reset_index(drop=True)
    return agg


def find_max_concurrency_under_sla(agg: pd.DataFrame) -> dict:
    """Per stack, where p95 TTFT sits relative to the SLA.

    Reports the per-level pass/fail lists alongside the headline number,
    because the SLA result is not monotonic for every stack: a stack can dip
    back under the threshold at a higher concurrency than one it breached.
    `consistent` is False in that case, and `sustained_concurrency` — the
    highest level reached before the *first* breach — is the honest headline
    for such a stack, since `max_concurrency_under_sla` alone would imply a
    clean pass it did not earn.
    """
    result = {}
    for stack in STACKS:
        sub = agg[agg["stack"] == stack].sort_values("concurrency")
        ok = sub[sub["ttft_p95_ms"] < TTFT_SLA_MS]

        under = [int(c) for c in sub[sub["ttft_p95_ms"] < TTFT_SLA_MS]["concurrency"]]
        over = [int(c) for c in sub[sub["ttft_p95_ms"] >= TTFT_SLA_MS]["concurrency"]]
        first_breach = min(over) if over else None

        # highest level reached before the first breach (None if it breached
        # at the very first level tested)
        sustained = None
        for _, row in sub.iterrows():
            if row["ttft_p95_ms"] >= TTFT_SLA_MS:
                break
            sustained = int(row["concurrency"])

        max_under = int(ok["concurrency"].max()) if not ok.empty else None
        # non-monotonic: it passed at some level above where it first breached
        consistent = max_under is None or first_breach is None or max_under < first_breach

        result[stack] = {
            "max_concurrency_under_sla": max_under,
            "sla_ms": TTFT_SLA_MS,
            "breached_at": first_breach,
            "levels_under_sla": under,
            "levels_over_sla": over,
            "sustained_concurrency": sustained,
            "consistent": bool(consistent),
        }
    return result


def load_kv_cache_results() -> list:
    path = ROOT / "experiment2_memory" / "kv_cache_results.csv"
    df = pd.read_csv(path)
    df["oom"] = df["oom"].astype(str).str.lower() == "true"
    records = df.to_dict(orient="records")
    # NaN is not valid JSON (json.dumps emits a bare `NaN` token that breaks
    # JSON.parse in the browser) — swap missing OOM-row values for None.
    # (Assigning None back into a float64 column via df.where reverts to NaN,
    # so the substitution has to happen per-record, after to_dict.)
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and pd.isna(v):
                rec[k] = None
    return records


def load_quantization_results() -> dict:
    path = ROOT / "experiment2_memory" / "quantization_results.json"
    data = json.loads(path.read_text())
    fp16, q4 = data["fp16"], data["4bit"]
    comparison = {
        "fp16": fp16,
        "4bit": q4,
        "mem_reduction_pct": round(
            (1 - q4["mem_at_rest_mb"] / fp16["mem_at_rest_mb"]) * 100, 1
        ),
        "speed_change_pct": round(
            (q4["tokens_per_second"] / fp16["tokens_per_second"] - 1) * 100, 1
        ),
        "note": "Single-trial comparison — not averaged across repeated runs; "
        "treat as directional, not statistically rigorous.",
    }
    return comparison


def build_hypothesis_check(agg: pd.DataFrame, sla_summary: dict) -> dict:
    c30 = agg[agg["concurrency"] == 30].set_index("stack")
    naive_tput = c30.loc["naive_hf", "tokens_per_s_est"] if "naive_hf" in c30.index else None
    vllm_tput = c30.loc["vllm", "tokens_per_s_est"] if "vllm" in c30.index else None
    throughput_ratio = (vllm_tput / naive_tput) if naive_tput else None

    vllm_p95_at_30 = c30.loc["vllm", "ttft_p95_ms"] if "vllm" in c30.index else None
    vllm_meets_ttft_sla_at_30 = bool(vllm_p95_at_30 is not None and vllm_p95_at_30 < TTFT_SLA_MS)

    return {
        "hypothesis": (
            "vLLM achieves ~5x throughput vs naive HF, and p95 TTFT stays under "
            "1s at 30 concurrent requests."
        ),
        "vllm_vs_naive_throughput_ratio_at_c30": (
            round(throughput_ratio, 2) if throughput_ratio else None
        ),
        "vllm_p95_ttft_ms_at_c30": (
            round(vllm_p95_at_30, 1) if vllm_p95_at_30 is not None else None
        ),
        "vllm_meets_ttft_sla_at_c30": vllm_meets_ttft_sla_at_30,
        "throughput_claim_confirmed": (
            bool(throughput_ratio and throughput_ratio >= 4.0) if throughput_ratio else None
        ),
    }


def main():
    avg_max_tokens = load_prompt_avg_max_tokens()
    print(f"Average max_tokens across prompt dataset: {avg_max_tokens:.2f}")

    raw = collect_raw_rows()
    agg = aggregate(raw, avg_max_tokens)

    print("\n=== Aggregated summary (median across 3 trials) ===")
    with pd.option_context("display.max_columns", None, "display.width", 160):
        print(
            agg[
                [
                    "stack",
                    "concurrency",
                    "ttft_median_ms",
                    "ttft_p95_ms",
                    "total_median_ms",
                    "total_p95_ms",
                    "requests_per_s",
                    "tokens_per_s_est",
                ]
            ].round(2)
        )

    sla_summary = find_max_concurrency_under_sla(agg)
    print("\n=== Max concurrency with p95 TTFT < 1000ms ===")
    for stack, info in sla_summary.items():
        print(f"  {STACK_LABELS[stack]}: {info}")

    kv_cache = load_kv_cache_results()
    quant = load_quantization_results()
    print("\n=== Quantization comparison ===")
    print(json.dumps(quant, indent=2))

    hypothesis = build_hypothesis_check(agg, sla_summary)
    print("\n=== Hypothesis check ===")
    print(json.dumps(hypothesis, indent=2))

    summary = {
        "meta": {
            "stacks": STACKS,
            "stack_labels": STACK_LABELS,
            "concurrencies": CONCURRENCIES,
            "trials_per_point": len(TRIALS),
            "ttft_sla_ms": TTFT_SLA_MS,
            "avg_max_tokens": round(avg_max_tokens, 2),
        },
        "per_stack_concurrency": json.loads(agg.round(3).to_json(orient="records")),
        "sla": sla_summary,
        "kv_cache": kv_cache,
        "quantization": quant,
        "hypothesis_check": hypothesis,
    }

    out_path = Path(__file__).resolve().parent / "summary.json"
    # allow_nan=False: fail loudly instead of emitting invalid JSON (`NaN`)
    # that would silently break JSON.parse in the browser.
    out_path.write_text(json.dumps(summary, indent=2, allow_nan=False))
    print(f"\nWrote {out_path}")

    # Also emit a flat CSV of the per-stack/concurrency aggregate for easy inspection
    csv_path = Path(__file__).resolve().parent / "summary.csv"
    agg.round(3).to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
