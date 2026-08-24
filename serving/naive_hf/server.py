from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
from threading import Thread

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

app = FastAPI()

print("Loading model...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
    device_map="cuda"
)
print("Model loaded.")

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 100

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/generate")
def generate(req: GenerateRequest):
    inputs = tokenizer(req.prompt, return_tensors="pt").to("cuda")
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

    generation_kwargs = dict(**inputs, max_new_tokens=req.max_tokens, streamer=streamer)
    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()

    def token_generator():
        import time as _time
        for token_text in streamer:
            print(f"[{_time.time():.3f}] yielded: {token_text!r}")
            yield token_text

    return StreamingResponse(token_generator(), media_type="text/plain")
