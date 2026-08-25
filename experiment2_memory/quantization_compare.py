import torch
import time
import gc
import json
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
TEST_PROMPT = "Explain what this code does:\n\ndef fib(n):\n    if n <= 1:\n        return n\n    return fib(n-1) + fib(n-2)"
MAX_NEW_TOKENS = 150

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
results = {}


def measure(label, model):
    torch.cuda.empty_cache()
    gc.collect()
    torch.cuda.reset_peak_memory_stats()

    mem_at_rest = torch.cuda.memory_allocated() / (1024 ** 2)

    inputs = tokenizer(TEST_PROMPT, return_tensors="pt").to("cuda")

    start = time.time()
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
    elapsed = time.time() - start

    text = tokenizer.decode(output[0], skip_special_tokens=True)
    peak_mem = torch.cuda.max_memory_allocated() / (1024 ** 2)

    results[label] = {
        "mem_at_rest_mb": round(mem_at_rest, 1),
        "peak_mem_mb": round(peak_mem, 1),
        "generation_seconds": round(elapsed, 2),
        "tokens_per_second": round(MAX_NEW_TOKENS / elapsed, 2),
        "output_sample": text
    }

    print(f"\n=== {label} ===")
    print(f"Memory at rest: {mem_at_rest:.1f} MB")
    print(f"Peak memory during generation: {peak_mem:.1f} MB")
    print(f"Generation time: {elapsed:.2f}s ({MAX_NEW_TOKENS / elapsed:.2f} tokens/sec)")
    print(f"Output sample: {text[:200]}...")


# --- FP16 baseline ---
print("Loading FP16 model...")
model_fp16 = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=torch.float16, device_map="cuda")
measure("fp16", model_fp16)

del model_fp16
torch.cuda.empty_cache()
gc.collect()

# --- 4-bit quantized ---
print("\nLoading 4-bit quantized model...")
quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
model_4bit = AutoModelForCausalLM.from_pretrained(MODEL_NAME, quantization_config=quant_config, device_map="cuda")
measure("4bit", model_4bit)

del model_4bit
torch.cuda.empty_cache()
gc.collect()

with open("quantization_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nDone. Results saved to quantization_results.json")

print("\n=== SUMMARY ===")
mem_saved = results["fp16"]["mem_at_rest_mb"] - results["4bit"]["mem_at_rest_mb"]
mem_saved_pct = (mem_saved / results["fp16"]["mem_at_rest_mb"]) * 100
speed_change_pct = ((results["4bit"]["tokens_per_second"] - results["fp16"]["tokens_per_second"])
                     / results["fp16"]["tokens_per_second"]) * 100
print(f"Memory saved by 4-bit: {mem_saved:.1f} MB ({mem_saved_pct:.1f}%)")
print(f"Speed change (4bit vs fp16): {speed_change_pct:+.1f}%")
