"""Initial schema: all tables in their current final form.

Revision ID: 001
Revises:
Create Date: 2026-05-31
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS torneos (
            torneo_id            INTEGER PRIMARY KEY,
            cat_id               INTEGER,
            comp_id              INTEGER,
            categoria_name       TEXT,
            competicion_name     TEXT,
            torneo_name          TEXT,
            jornadas_discovered  INTEGER DEFAULT 0,
            season_id            TEXT NOT NULL DEFAULT '2526'
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS jornadas (
            torneo_id   INTEGER,
            jornada_num INTEGER,
            scraped     INTEGER DEFAULT 0,
            PRIMARY KEY (torneo_id, jornada_num)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id        INTEGER PRIMARY KEY,
            torneo_id       INTEGER,
            home_team       TEXT,
            away_team       TEXT,
            date            TEXT,
            time            TEXT,
            venue           TEXT,
            status          TEXT,
            referee_scraped INTEGER DEFAULT 0,
            scraped_at      TEXT,
            score_home      INTEGER,
            score_away      INTEGER
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS referees (
            match_id       INTEGER PRIMARY KEY,
            referee_1      TEXT,
            referee_2      TEXT,
            scorekeeper_1  TEXT,
            scorekeeper_2  TEXT,
            table_delegate TEXT,
            tv             TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS referees_catalog (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_name    TEXT,
            normalized  TEXT,
            category    TEXT,
            territory   TEXT,
            active      INTEGER DEFAULT 1,
            season_id   TEXT DEFAULT '2526'
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_name_season
        ON referees_catalog (raw_name, season_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS nomination_scores (
            match_id         INTEGER,
            referee_name     TEXT,
            catalog_id       INTEGER,
            competition_mod  REAL,
            match_quality    REAL,
            score_factor     REAL,
            nomination_score REAL,
            rank_home        INTEGER,
            rank_away        INTEGER,
            n_teams          INTEGER,
            PRIMARY KEY (match_id, referee_name)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS nomination_scores")
    op.execute("DROP INDEX IF EXISTS idx_catalog_name_season")
    op.execute("DROP TABLE IF EXISTS referees_catalog")
    op.execute("DROP TABLE IF EXISTS referees")
    op.execute("DROP TABLE IF EXISTS matches")
    op.execute("DROP TABLE IF EXISTS jornadas")
    op.execute("DROP TABLE IF EXISTS torneos")
    op.execute("DROP TABLE IF EXISTS meta")
