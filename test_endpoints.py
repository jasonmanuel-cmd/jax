"""Test JAX server endpoints."""
import urllib.request
import json

TOKEN = "jax-admin-token-2026-secure-key!"
BASE = "http://127.0.0.1:8788"

def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode()

def get(path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {TOKEN}"}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode()

# Health
print("=== /health ===")
print(get("/health"))

# Chat
print("\n=== /v1/chat ===")
status, body = post("/v1/chat", {"query": "What is JAX?"})
print(f"Status: {status}")
data = json.loads(body)
print(f"Answer: {data['answer'][:200]}")
print(f"Model: {data['model_used']}")

# Kill switch status
print("\n=== /v1/kill/status ===")
status, body = get("/v1/kill/status")
print(body)

# Voice speak
print("\n=== /v1/voice/speak ===")
try:
    status, body = post("/v1/voice/speak", {"text": "Hello from JAX"})
    print(f"Status: {status}")
    with open("C:/Users/blunts/Desktop/jax_speak.mp3", "wb") as f:
        f.write(body)
    print("Audio saved to C:/Users/blunts/Desktop/jax_speak.mp3")
except Exception as e:
    print(f"Error: {e}")
