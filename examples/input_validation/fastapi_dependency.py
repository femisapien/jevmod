"""FastAPI dependency that moderates the request body; a hit answers 422 with the category and probability.

uvicorn examples.input_validation.fastapi_dependency:app --port 8000
curl -X POST localhost:8000/comments -H "Content-Type: application/json" -d '{"text":"hello from valencia"}'
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from jevmod import Moderator

app = FastAPI(title="comments")
mod = Moderator()


class Comment(BaseModel):
    text: str = Field(..., max_length=4000)
    topic: str = ""


def moderated(comment: Comment) -> Comment:
    d = mod.check(comment.text, channel_topic=comment.topic)
    if d.action != "none":
        raise HTTPException(422, {"error": "rejected", "category": d.category, "probability": round(d.probability, 2)})
    return comment


@app.post("/comments")
def post_comment(comment: Annotated[Comment, Depends(moderated)]) -> dict[str, str]:
    return {"stored": comment.text}
