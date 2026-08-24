import time
import json
import random
from pathlib import Path
from locust import HttpUser, task, between, events

PROMPTS_PATH = Path(__file__).parent / "prompts" / "prompt_dataset.json"
with open(PROMPTS_PATH) as f:
    PROMPTS = json.load(f)


class BenchmarkUser(HttpUser):
    wait_time = between(0, 0)  # fire requests back-to-back, no artificial delay

    @task
    def generate(self):
        prompt_obj = random.choice(PROMPTS)
        start = time.time()
        first_byte_time = None

        with self.client.post("/generate", json=prompt_obj, stream=True, catch_response=True) as response:
            try:
                for chunk in response.iter_content(chunk_size=None):
                    if first_byte_time is None:
                        first_byte_time = time.time()
                end = time.time()

                if first_byte_time is None:
                    response.failure("No data received")
                    return

                ttft_ms = (first_byte_time - start) * 1000
                total_ms = (end - start) * 1000

                events.request.fire(
                    request_type="TTFT",
                    name="/generate",
                    response_time=ttft_ms,
                    response_length=0,
                    exception=None,
                )
                events.request.fire(
                    request_type="TOTAL",
                    name="/generate",
                    response_time=total_ms,
                    response_length=0,
                    exception=None,
                )
                response.success()
            except Exception as e:
                response.failure(str(e))
