"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-28

This migration's DDL is mechanically derived from backend/app/models/* (via
sqlalchemy.create_mock_engine against Base.metadata) rather than hand-typed, so it cannot
drift from the ORM models it was generated from. Regenerate with:

    python -c "
    from sqlalchemy import create_mock_engine
    from backend.app.models import Base
    statements = []
    def dump(sql, *a, **k): statements.append(str(sql.compile(dialect=mock_engine.dialect)))
    mock_engine = create_mock_engine('postgresql+psycopg://', dump)
    Base.metadata.create_all(mock_engine, checkfirst=False)
    "
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_TYPES = [
    "call_source",
    "call_status",
    "step_status",
    "sentiment",
    "audio_variant",
    "ingestion_source_type",
    "rule_type",
    "speaker_scope",
    "scoring_logic",
    "evaluation_mode",
    "evaluation_status",
    "verdict",
    "evidence_type",
    "review_action_type",
]

# Table names in FK-dependency order (matches Base.metadata.sorted_tables), used to drop
# in reverse order on downgrade.
TABLES_IN_ORDER = [
    "speaker_roles",
    "organizations",
    "roles",
    "permissions",
    "ingestion_sources",
    "role_permissions",
    "users",
    "projects",
    "departments",
    "audit_log",
    "scorecards",
    "teams",
    "scorecard_sections",
    "team_members",
    "agents",
    "scorecard_criteria",
    "calls",
    "call_tags",
    "call_flags",
    "call_processing_steps",
    "processing_jobs",
    "speakers",
    "acoustic_metrics",
    "call_summaries",
    "qa_evaluations",
    "utterances",
    "qa_findings",
    "utterance_corrections",
    "comments",
    "qa_finding_evidence",
    "review_actions",
]


def upgrade() -> None:
    op.execute("CREATE TYPE call_source AS ENUM ('upload', 'voiso', 'asterisk', 'sftp', 'api', 'csv_import')")
    op.execute(
        "CREATE TYPE call_status AS ENUM ('uploaded', 'queued', 'preprocessing', 'diarizing', "
        "'transcribing', 'aligning', 'assigning_speakers', 'analyzing', 'completed', 'failed', 'cancelled')"
    )
    op.execute("CREATE TYPE step_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'skipped')")
    op.execute("CREATE TYPE sentiment AS ENUM ('Neutral', 'Positive', 'Negative')")
    op.execute("CREATE TYPE audio_variant AS ENUM ('original', 'enhanced', 'vocals')")
    op.execute(
        "CREATE TYPE ingestion_source_type AS ENUM ('voiso', 'asterisk', 'sftp', 'object_storage', "
        "'rest_api', 'webhook', 'csv_import')"
    )
    op.execute(
        "CREATE TYPE rule_type AS ENUM ('keyword', 'regex', 'sequence', 'timing', "
        "'silence_interruption', 'speaker_behavior', 'script_compliance', 'semantic', 'hybrid', 'manual_only')"
    )
    op.execute("CREATE TYPE speaker_scope AS ENUM ('agent', 'client', 'any')")
    op.execute("CREATE TYPE scoring_logic AS ENUM ('pass_fail', 'numeric', 'weighted')")
    op.execute("CREATE TYPE evaluation_mode AS ENUM ('automatic', 'ai_assisted', 'manual_only')")
    op.execute("CREATE TYPE evaluation_status AS ENUM ('pending_review', 'reviewed')")
    op.execute("CREATE TYPE verdict AS ENUM ('pass', 'fail', 'na')")
    op.execute("CREATE TYPE evidence_type AS ENUM ('violation', 'positive')")
    op.execute(
        "CREATE TYPE review_action_type AS ENUM ('confirm', 'reject', 'correct', "
        "'add_evidence', 'remove_evidence', 'reopen')"
    )

    op.execute("""
        CREATE TABLE speaker_roles (
            code VARCHAR(50) NOT NULL,
            label VARCHAR(100) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (code)
        )
    """)

    op.execute("""
        CREATE TABLE organizations (
            name VARCHAR(255) NOT NULL,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id)
        )
    """)

    op.execute("""
        CREATE TABLE roles (
            code VARCHAR(50) NOT NULL,
            label VARCHAR(100) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (code)
        )
    """)

    op.execute("""
        CREATE TABLE permissions (
            code VARCHAR(100) NOT NULL,
            label VARCHAR(255) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (code)
        )
    """)

    op.execute("""
        CREATE TABLE ingestion_sources (
            org_id UUID NOT NULL,
            type ingestion_source_type NOT NULL,
            config JSONB NOT NULL,
            is_active BOOLEAN NOT NULL,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(org_id) REFERENCES organizations (id)
        )
    """)

    op.execute("""
        CREATE TABLE role_permissions (
            role_id UUID NOT NULL,
            permission_id UUID NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_role_permission UNIQUE (role_id, permission_id),
            FOREIGN KEY(role_id) REFERENCES roles (id),
            FOREIGN KEY(permission_id) REFERENCES permissions (id)
        )
    """)

    op.execute("""
        CREATE TABLE users (
            org_id UUID NOT NULL,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            role_id UUID NOT NULL,
            is_active BOOLEAN NOT NULL,
            deactivated_at TIMESTAMP WITH TIME ZONE,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(org_id) REFERENCES organizations (id),
            UNIQUE (email),
            FOREIGN KEY(role_id) REFERENCES roles (id)
        )
    """)

    op.execute("""
        CREATE TABLE projects (
            org_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            description VARCHAR(1000),
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(org_id) REFERENCES organizations (id)
        )
    """)

    op.execute("""
        CREATE TABLE departments (
            project_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(project_id) REFERENCES projects (id)
        )
    """)

    op.execute("""
        CREATE TABLE audit_log (
            org_id UUID NOT NULL,
            user_id UUID,
            action VARCHAR(100) NOT NULL,
            entity_type VARCHAR(100) NOT NULL,
            entity_id UUID,
            audit_metadata JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(org_id) REFERENCES organizations (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE scorecards (
            group_id UUID NOT NULL,
            version INTEGER NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            project_id UUID NOT NULL,
            is_active BOOLEAN NOT NULL,
            published_at TIMESTAMP WITH TIME ZONE,
            created_by UUID NOT NULL,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(project_id) REFERENCES projects (id),
            FOREIGN KEY(created_by) REFERENCES users (id)
        )
    """)
    op.execute("CREATE INDEX ix_scorecards_group_id ON scorecards (group_id)")

    op.execute("""
        CREATE TABLE teams (
            project_id UUID NOT NULL,
            department_id UUID,
            name VARCHAR(255) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(project_id) REFERENCES projects (id),
            FOREIGN KEY(department_id) REFERENCES departments (id)
        )
    """)

    op.execute("""
        CREATE TABLE scorecard_sections (
            scorecard_id UUID NOT NULL,
            name VARCHAR(255) NOT NULL,
            order_index INTEGER NOT NULL,
            weight NUMERIC NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(scorecard_id) REFERENCES scorecards (id)
        )
    """)

    op.execute("""
        CREATE TABLE team_members (
            team_id UUID NOT NULL,
            user_id UUID NOT NULL,
            is_lead BOOLEAN NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_team_member UNIQUE (team_id, user_id),
            FOREIGN KEY(team_id) REFERENCES teams (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE agents (
            team_id UUID NOT NULL,
            user_id UUID,
            full_name VARCHAR(255) NOT NULL,
            external_id VARCHAR(255),
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(team_id) REFERENCES teams (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE scorecard_criteria (
            section_id UUID NOT NULL,
            code VARCHAR(100) NOT NULL,
            text TEXT NOT NULL,
            rule_type rule_type NOT NULL,
            weight NUMERIC NOT NULL,
            is_optional BOOLEAN NOT NULL,
            is_critical BOOLEAN NOT NULL,
            requires_evidence BOOLEAN NOT NULL,
            threshold JSONB,
            keywords JSONB,
            semantic_instruction TEXT,
            speaker_scope speaker_scope NOT NULL,
            timing_scope JSONB,
            scoring_logic scoring_logic NOT NULL,
            evaluation_mode evaluation_mode NOT NULL,
            order_index INTEGER NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(section_id) REFERENCES scorecard_sections (id)
        )
    """)

    op.execute("""
        CREATE TABLE calls (
            org_id UUID NOT NULL,
            project_id UUID NOT NULL,
            agent_id UUID,
            uploaded_by UUID NOT NULL,
            source call_source NOT NULL,
            external_call_id VARCHAR(255),
            original_filename VARCHAR(500) NOT NULL,
            storage_path VARCHAR(1000) NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            duration_seconds NUMERIC,
            file_size_bytes INTEGER,
            detected_language VARCHAR(10),
            status call_status NOT NULL,
            uploaded_at TIMESTAMP WITH TIME ZONE NOT NULL,
            processed_at TIMESTAMP WITH TIME ZONE,
            retention_expires_at TIMESTAMP WITH TIME ZONE,
            deleted_at TIMESTAMP WITH TIME ZONE,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(org_id) REFERENCES organizations (id),
            FOREIGN KEY(project_id) REFERENCES projects (id),
            FOREIGN KEY(agent_id) REFERENCES agents (id),
            FOREIGN KEY(uploaded_by) REFERENCES users (id)
        )
    """)
    op.execute("CREATE INDEX ix_calls_checksum ON calls (checksum)")

    op.execute("""
        CREATE TABLE call_tags (
            call_id UUID NOT NULL,
            tag VARCHAR(100) NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id)
        )
    """)

    op.execute("""
        CREATE TABLE call_flags (
            call_id UUID NOT NULL,
            flag_type VARCHAR(100) NOT NULL,
            raised_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id),
            FOREIGN KEY(raised_by) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE call_processing_steps (
            call_id UUID NOT NULL,
            step_name VARCHAR(100) NOT NULL,
            sequence INTEGER NOT NULL,
            status step_status NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            error_message TEXT,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT uq_call_processing_step UNIQUE (call_id, step_name),
            FOREIGN KEY(call_id) REFERENCES calls (id)
        )
    """)

    op.execute("""
        CREATE TABLE processing_jobs (
            call_id UUID NOT NULL,
            celery_task_id VARCHAR(255) NOT NULL,
            attempt INTEGER NOT NULL,
            status VARCHAR(50) NOT NULL,
            last_error TEXT,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id)
        )
    """)

    op.execute("""
        CREATE TABLE speakers (
            call_id UUID NOT NULL,
            diarization_label VARCHAR(50) NOT NULL,
            role_id UUID NOT NULL,
            display_name VARCHAR(255),
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id),
            FOREIGN KEY(role_id) REFERENCES speaker_roles (id)
        )
    """)

    op.execute("""
        CREATE TABLE acoustic_metrics (
            call_id UUID NOT NULL,
            source_audio_variant audio_variant NOT NULL,
            rms_loudness NUMERIC,
            zero_crossing_rate NUMERIC,
            spectral_centroid NUMERIC,
            eq_20_250 NUMERIC,
            eq_250_2000 NUMERIC,
            eq_2000_6000 NUMERIC,
            eq_6000_20000 NUMERIC,
            mfcc_1 NUMERIC, mfcc_2 NUMERIC, mfcc_3 NUMERIC, mfcc_4 NUMERIC, mfcc_5 NUMERIC,
            mfcc_6 NUMERIC, mfcc_7 NUMERIC, mfcc_8 NUMERIC, mfcc_9 NUMERIC, mfcc_10 NUMERIC,
            mfcc_11 NUMERIC, mfcc_12 NUMERIC, mfcc_13 NUMERIC,
            silence_ratio NUMERIC,
            interruption_count INTEGER,
            agent_talk_ratio NUMERIC,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (call_id),
            FOREIGN KEY(call_id) REFERENCES calls (id)
        )
    """)

    op.execute("""
        CREATE TABLE call_summaries (
            call_id UUID NOT NULL,
            summary_text TEXT,
            conflict_detected BOOLEAN NOT NULL,
            conflict_details TEXT,
            topics JSONB NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (call_id),
            FOREIGN KEY(call_id) REFERENCES calls (id)
        )
    """)

    op.execute("""
        CREATE TABLE qa_evaluations (
            call_id UUID NOT NULL,
            scorecard_id UUID NOT NULL,
            overall_score NUMERIC,
            max_score NUMERIC,
            status evaluation_status NOT NULL,
            id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id),
            FOREIGN KEY(scorecard_id) REFERENCES scorecards (id)
        )
    """)

    op.execute("""
        CREATE TABLE utterances (
            call_id UUID NOT NULL,
            speaker_id UUID NOT NULL,
            sequence INTEGER NOT NULL,
            start_time NUMERIC NOT NULL,
            end_time NUMERIC NOT NULL,
            original_content TEXT NOT NULL,
            sentiment sentiment,
            is_profane BOOLEAN NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id),
            FOREIGN KEY(speaker_id) REFERENCES speakers (id)
        )
    """)

    op.execute("""
        CREATE TABLE qa_findings (
            evaluation_id UUID NOT NULL,
            criterion_id UUID NOT NULL,
            ai_verdict verdict NOT NULL,
            ai_confidence NUMERIC,
            ai_explanation TEXT,
            engine_version VARCHAR(50) NOT NULL,
            current_verdict verdict NOT NULL,
            human_corrected BOOLEAN NOT NULL,
            reviewed_by UUID,
            reviewed_at TIMESTAMP WITH TIME ZONE,
            notes TEXT,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(evaluation_id) REFERENCES qa_evaluations (id),
            FOREIGN KEY(criterion_id) REFERENCES scorecard_criteria (id),
            FOREIGN KEY(reviewed_by) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE utterance_corrections (
            utterance_id UUID NOT NULL,
            corrected_content TEXT,
            corrected_speaker_id UUID,
            corrected_by UUID NOT NULL,
            reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(utterance_id) REFERENCES utterances (id),
            FOREIGN KEY(corrected_speaker_id) REFERENCES speakers (id),
            FOREIGN KEY(corrected_by) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE comments (
            call_id UUID NOT NULL,
            utterance_id UUID,
            user_id UUID NOT NULL,
            body TEXT NOT NULL,
            parent_comment_id UUID,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(call_id) REFERENCES calls (id),
            FOREIGN KEY(utterance_id) REFERENCES utterances (id),
            FOREIGN KEY(user_id) REFERENCES users (id),
            FOREIGN KEY(parent_comment_id) REFERENCES comments (id)
        )
    """)

    op.execute("""
        CREATE TABLE qa_finding_evidence (
            finding_id UUID NOT NULL,
            utterance_id UUID,
            start_time NUMERIC NOT NULL,
            end_time NUMERIC NOT NULL,
            quote_text TEXT NOT NULL,
            evidence_type evidence_type NOT NULL,
            added_by UUID,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(finding_id) REFERENCES qa_findings (id),
            FOREIGN KEY(utterance_id) REFERENCES utterances (id),
            FOREIGN KEY(added_by) REFERENCES users (id)
        )
    """)

    op.execute("""
        CREATE TABLE review_actions (
            finding_id UUID NOT NULL,
            action_type review_action_type NOT NULL,
            previous_verdict verdict,
            new_verdict verdict,
            user_id UUID NOT NULL,
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            id UUID NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(finding_id) REFERENCES qa_findings (id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """)


def downgrade() -> None:
    for table in reversed(TABLES_IN_ORDER):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for enum_type in reversed(ENUM_TYPES):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
