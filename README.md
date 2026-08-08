# research-assistant

FastAPI app with a `POST /ask` endpoint that calls an LLM via OpenRouter.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in `OPENROUTER_API_KEY`.

## Run

```bash
uvicorn main:app --reload
```

## Test

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is FastAPI?"}'
```

## Response shape

```json
{
  "answer": "...",
  "sources": [],
  "confidence": 1.0,
  "model": "gpt-4o-mini",
  "tokens_used": 150
}
```
