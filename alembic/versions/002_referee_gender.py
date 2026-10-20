"""Add gender and gender_confidence columns to referees_catalog, populate via name detection.

Revision ID: 002
Revises: 001
Create Date: 2026-05-31
"""

from alembic import op

revision = "002"
down_revision = "001"


def upgrade() -> None:
    import sys
    from pathlib import Path
    from sqlalchemy import text
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import gender_detector

    conn = op.get_bind()
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(referees_catalog)")).fetchall()}
    if "gender" not in cols:
        op.execute(text("ALTER TABLE referees_catalog ADD COLUMN gender TEXT NOT NULL DEFAULT ''"))
    if "gender_confidence" not in cols:
        op.execute(text("ALTER TABLE referees_catalog ADD COLUMN gender_confidence REAL NOT NULL DEFAULT 0.0"))

    rows = conn.execute(text("SELECT id, raw_name FROM referees_catalog")).fetchall()
    for row_id, raw_name in rows:
        g, conf = gender_detector.detect(raw_name or "")
        conn.execute(
            text("UPDATE referees_catalog SET gender=:g, gender_confidence=:c WHERE id=:id"),
            {"g": g, "c": round(conf, 2), "id": row_id},
        )


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN in older versions; recreate without the columns
    op.execute("""
        CREATE TABLE referees_catalog_backup AS
        SELECT id, raw_name, normalized, category, territory, active, season_id
        FROM referees_catalog
    """)
    op.execute("DROP TABLE referees_catalog")
    op.execute("ALTER TABLE referees_catalog_backup RENAME TO referees_catalog")
