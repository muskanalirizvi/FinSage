from backend.config import get_llm

llm = get_llm("writer")
print("max_tokens in use:", llm.max_tokens)

try:
    print(llm.invoke("Reply with exactly one word: ready").content)
except Exception as e:
    print(e)