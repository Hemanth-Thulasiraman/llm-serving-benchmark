import time
import json
import random
import os
import requests
from pathlib import Path
from locust import HttpUser, task, between, events

PROMPTS_PATH = Path(__file__).parent / "prompts" / "prompt_dataset.json"
with open(PROMPTS_PATH) as f:
    PROMPTS = json.load(f)

STACK = os.environ.get("BENCHMARK_STACK", "naive_hf")

adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)


def build_request(prompt_obj):
    if STACK == "tgi":
        return "/generate_stream", {
            "inputs": prompt_obj["prompt"],
            "parameters": {"max_new_tokens": prompt_obj["max_tokens"]}
        }
    elif STACK == "vllm":
        return "/v1/completions", {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "prompt": prompt_obj["prompt"],
            "max_tokens": prompt_obj["max_tokens"],
            "stream": True
        }
    else:  # naive_hf
        return "/generate", {
            "prompt": prompt_obj["prompt"],
            "max_tokens": prompt_obj["max_tokens"]
        }


class BenchmarkUser(HttpUser):
    wait_time = between(0, 0)

    @task
    def generate(self):
        prompt_obj = random.choice(PROMPTS)
        path, payload = build_request(prompt_obj)
        headers = {"Authorization": f"Bearer {os.environ.get('VLLM_API_KEY', '')}"} if STACK == "vllm" else {}
        start = time.time()
        first_byte_time = None

        try:
            response = session.post(self.host + path, json=payload, headers=headers, stream=True, timeout=60)
            for chunk in response.iter_content(chunk_size=None):
                if first_byte_time is None:
                    first_byte_time = time.time()
            end = time.time()

            if first_byte_time is None:
                events.request.fire(request_type="TOTAL", name="/generate", response_time=(end - start) * 1000,
                                     response_length=0, exception=Exception("No data received"))
                return

            events.request.fire(request_type="TTFT", name="/generate",
                                 response_time=(first_byte_time - start) * 1000, response_length=0, exception=None)
            events.request.fire(request_type="TOTAL", name="/generate",
                                 response_time=(end - start) * 1000, response_length=0, exception=None)
        except Exception as e:
            events.request.fire(request_type="TOTAL", name="/generate", response_time=0, response_length=0, exception=e)
