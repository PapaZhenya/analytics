from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.dependencies import require_permission
from backend.app.models.org import Project, User
from backend.app.schemas.org import ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    user: User = Depends(require_permission("calls.view")),
    db: Session = Depends(get_db),
) -> list[Project]:
    return db.query(Project).filter(Project.org_id == user.org_id).order_by(Project.name).all()
