import torch
import csv
import gc
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

print("Loading model...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
    device_map="cuda"
)
model.eval()
print("Model loaded.")

CONTEXT_LENGTHS = [512, 1024, 2048, 4096]
CONCURRENCY_LEVELS = [1, 5, 10, 20]

results = []

for context_len in CONTEXT_LENGTHS:
    for concurrency in CONCURRENCY_LEVELS:
        torch.cuda.empty_cache()
        gc.collect()
        torch.cuda.reset_peak_memory_stats()

        mem_before = torch.cuda.memory_allocated() / (1024 ** 2)  # MB

        input_ids = torch.randint(0, tokenizer.vocab_size, (concurrency, context_len)).to("cuda")

        try:
            with torch.no_grad():
                outputs = model(input_ids, use_cache=True)

            mem_after = torch.cuda.memory_allocated() / (1024 ** 2)  # MB
            mem_peak = torch.cuda.max_memory_allocated() / (1024 ** 2)  # MB
            kv_cache_mb = mem_after - mem_before

            print(f"context={context_len} concurrency={concurrency} "
                  f"before={mem_before:.1f}MB after={mem_after:.1f}MB "
                  f"kv_cache~={kv_cache_mb:.1f}MB peak={mem_peak:.1f}MB")

            results.append({
                "context_length": context_len,
                "concurrency": concurrency,
                "mem_before_mb": round(mem_before, 1),
                "mem_after_mb": round(mem_after, 1),
                "kv_cache_estimate_mb": round(kv_cache_mb, 1),
                "peak_mem_mb": round(mem_peak, 1),
                "oom": False
            })

            del outputs

        except torch.cuda.OutOfMemoryError:
            print(f"context={context_len} concurrency={concurrency} -- OOM")
            results.append({
                "context_length": context_len,
                "concurrency": concurrency,
                "mem_before_mb": round(mem_before, 1),
                "mem_after_mb": None,
                "kv_cache_estimate_mb": None,
                "peak_mem_mb": None,
                "oom": True
            })

        del input_ids
        torch.cuda.empty_cache()
        gc.collect()

with open("kv_cache_results.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print("Done. Results saved to kv_cache_results.csv")
