from backend.config import MODELS, get_llm

for role, cfg in MODELS.items():
    try:
        reply = get_llm(role).invoke("Reply with exactly one word: ready")
        print(f"OK    {role:<10} {cfg['model']:<28} -> {str(reply.content).strip()[:40]}")
    except Exception as e:
        print(f"FAIL  {role:<10} {cfg['model']:<28} -> {str(e)[:150]}")
