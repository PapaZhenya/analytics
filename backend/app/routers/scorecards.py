import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.org import User
from backend.app.models.qa import Scorecard
from backend.app.schemas.scorecards import ScorecardDetail, ScorecardListItem

router = APIRouter(prefix="/scorecards", tags=["scorecards"])


@router.get("", response_model=list[ScorecardListItem])
def list_scorecards(
    project_id: uuid.UUID | None = None,
    active_only: bool = True,
    user: User = Depends(require_permission("scorecards.view")),
    db: Session = Depends(get_db),
) -> list[Scorecard]:
    query = db.query(Scorecard)
    if project_id is not None:
        query = query.filter(Scorecard.project_id == project_id)
    if active_only:
        query = query.filter(Scorecard.is_active.is_(True))
    return query.order_by(Scorecard.name, Scorecard.version.desc()).all()


@router.get("/{scorecard_id}", response_model=ScorecardDetail)
def get_scorecard(
    scorecard_id: uuid.UUID,
    user: User = Depends(require_permission("scorecards.view")),
    db: Session = Depends(get_db),
) -> Scorecard:
    scorecard = db.get(Scorecard, scorecard_id)
    if scorecard is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scorecard not found")
    return scorecard
