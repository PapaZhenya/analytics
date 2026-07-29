import uuid

from pydantic import BaseModel


class CriterionOut(BaseModel):
    id: uuid.UUID
    code: str
    text: str
    rule_type: str
    weight: float
    is_optional: bool
    is_critical: bool
    requires_evidence: bool
    speaker_scope: str
    scoring_logic: str
    evaluation_mode: str
    order_index: int

    model_config = {"from_attributes": True}


class SectionOut(BaseModel):
    id: uuid.UUID
    name: str
    order_index: int
    weight: float
    criteria: list[CriterionOut]

    model_config = {"from_attributes": True}


class ScorecardListItem(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    version: int
    name: str
    project_id: uuid.UUID
    is_active: bool

    model_config = {"from_attributes": True}


class ScorecardDetail(ScorecardListItem):
    description: str | None
    sections: list[SectionOut]
