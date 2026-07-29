"""Seeds one example, published, active scorecard for the default Phase 1 project so
there's something to evaluate calls against out of the box. Run after
create_superuser.py (a scorecard needs an existing user as created_by).

Usage:
    python -m backend.scripts.seed_example_scorecard
"""
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, ".")

from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.models.org import Project, User  # noqa: E402
from backend.app.models.qa import (  # noqa: E402
    EvaluationMode,
    RuleType,
    Scorecard,
    ScorecardCriterion,
    ScorecardSection,
    ScoringLogic,
    SpeakerScope,
)


def main() -> None:
    db = SessionLocal()
    try:
        project = db.query(Project).first()
        if project is None:
            print("No project found — run `alembic upgrade head` first.", file=sys.stderr)
            sys.exit(1)

        creator = db.query(User).first()
        if creator is None:
            print("No user found — run create_superuser.py first.", file=sys.stderr)
            sys.exit(1)

        now = datetime.now(timezone.utc)
        scorecard = Scorecard(
            id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            version=1,
            name="Standard Call Quality (Example)",
            description="Seeded Phase 1 example scorecard — replace via the admin "
            "console once the no-code scorecard builder (Phase 2) ships.",
            project_id=project.id,
            is_active=True,
            published_at=now,
            created_by=creator.id,
        )
        db.add(scorecard)
        db.flush()

        opening_section = ScorecardSection(
            id=uuid.uuid4(), scorecard_id=scorecard.id, name="Opening", order_index=0, weight=1,
        )
        conduct_section = ScorecardSection(
            id=uuid.uuid4(), scorecard_id=scorecard.id, name="Professional Conduct", order_index=1, weight=1,
        )
        db.add_all([opening_section, conduct_section])
        db.flush()

        db.add_all(
            [
                ScorecardCriterion(
                    id=uuid.uuid4(),
                    section_id=opening_section.id,
                    code="greeting",
                    text="Agent greets the caller with a proper company greeting.",
                    rule_type=RuleType.keyword,
                    weight=1,
                    is_optional=False,
                    is_critical=False,
                    requires_evidence=True,
                    keywords={
                        "phrases": ["thank you for calling", "how can i help you"],
                        "mode": "must_include",
                    },
                    speaker_scope=SpeakerScope.agent,
                    scoring_logic=ScoringLogic.pass_fail,
                    evaluation_mode=EvaluationMode.automatic,
                    order_index=0,
                ),
                ScorecardCriterion(
                    id=uuid.uuid4(),
                    section_id=conduct_section.id,
                    code="empathy",
                    text="Agent demonstrates empathy and does not sound dismissive or rude.",
                    rule_type=RuleType.semantic,
                    weight=2,
                    is_optional=False,
                    is_critical=True,
                    requires_evidence=True,
                    semantic_instruction=(
                        "Determine whether the agent showed empathy toward the client and did "
                        "not sound dismissive, rude, or impatient at any point in the call."
                    ),
                    speaker_scope=SpeakerScope.agent,
                    scoring_logic=ScoringLogic.pass_fail,
                    evaluation_mode=EvaluationMode.ai_assisted,
                    order_index=0,
                ),
            ]
        )
        db.commit()
        print(f"Seeded scorecard {scorecard.id} for project {project.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
