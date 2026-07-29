import uuid


from pydantic import BaseModel


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class TeamOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    department_id: uuid.UUID | None
    name: str

    model_config = {"from_attributes": True}
