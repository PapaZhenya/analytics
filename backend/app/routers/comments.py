import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.calls import Call
from backend.app.models.collab import Comment
from backend.app.models.org import User
from backend.app.schemas.calls import CommentOut
from backend.app.schemas.comments import CommentCreate

router = APIRouter(prefix="/calls", tags=["comments"])


@router.get("/{call_id}/comments", response_model=list[CommentOut])
def list_comments(
    call_id: uuid.UUID,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> list[Comment]:
    if db.get(Call, call_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")
    return (
        db.query(Comment).filter(Comment.call_id == call_id).order_by(Comment.created_at).all()
    )


@router.post("/{call_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(
    call_id: uuid.UUID,
    body: CommentCreate,
    user: User = Depends(require_permission("comments.create")),
    db: Session = Depends(get_db),
) -> Comment:
    if db.get(Call, call_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Call not found")

    comment = Comment(
        id=uuid.uuid4(),
        call_id=call_id,
        utterance_id=body.utterance_id,
        user_id=user.id,
        body=body.body,
        parent_comment_id=body.parent_comment_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
