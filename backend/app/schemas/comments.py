import uuid

from pydantic import BaseModel


class CommentCreate(BaseModel):
    body: str
    utterance_id: uuid.UUID | None = None
    parent_comment_id: uuid.UUID | None = None
