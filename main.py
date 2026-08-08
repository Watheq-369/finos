import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "openai/gpt-4o-mini"

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

app = FastAPI()


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    confidence: float
    model: str
    tokens_used: int


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is not set")

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": request.question}],
    )
    answer = completion.choices[0].message.content
    tokens_used = completion.usage.total_tokens

    # no retrieval step yet, so sources/confidence are placeholders until a RAG step is added
    return AskResponse(
        answer=answer,
        sources=[],
        confidence=1.0,
        model="gpt-4o-mini",
        tokens_used=tokens_used,
    )
