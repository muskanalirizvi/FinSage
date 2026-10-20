import os

import requests

from backend import config  # noqa: F401  (loads your .env)

r = requests.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
    timeout=15,
)
r.raise_for_status()
for model_id in sorted(m["id"] for m in r.json()["data"]):
    print(model_id)