from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import time

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

app = FastAPI()

print("Loading model, this takes a minute...")
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
    start = time.time()
    inputs = tokenizer(req.prompt, return_tensors="pt").to("cuda")
    output = model.generate(**inputs, max_new_tokens=req.max_tokens)
    text = tokenizer.decode(output[0], skip_special_tokens=True)
    elapsed = time.time() - start
    return {"text": text, "latency_seconds": elapsed}
