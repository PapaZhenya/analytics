import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.org import Team, User
from backend.app.schemas.org import TeamOut

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[TeamOut])
def list_teams(
    project_id: uuid.UUID | None = None,
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> list[Team]:
    query = db.query(Team)
    if project_id is not None:
        query = query.filter(Team.project_id == project_id)
    return query.order_by(Team.name).all()
