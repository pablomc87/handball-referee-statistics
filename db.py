import json
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

import config

_write_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            -- Referee catalog parsed from PDFs
            CREATE TABLE IF NOT EXISTS referees_catalog (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_name    TEXT,
                normalized  TEXT,
                category    TEXT,   -- elite | honor | primera
                territory   TEXT,
                active      INTEGER DEFAULT 1,
                season_id   TEXT    DEFAULT '2526'
            );

            -- Computed nomination scores
            CREATE TABLE IF NOT EXISTS nomination_scores (
                match_id            INTEGER,
                referee_name        TEXT,
                catalog_id          INTEGER,
                competition_mod     REAL,
                match_quality       REAL,
                score_factor        REAL,
                nomination_score    REAL,
                PRIMARY KEY (match_id, referee_name)
            );
        """)

        # Migrate legacy meta key to season-specific format
        try:
            old = conn.execute("SELECT value FROM meta WHERE key='competitions_discovered'").fetchone()
            if old and old["value"] == "1":
                conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('competitions_discovered_2526','1')")
                conn.execute("DELETE FROM meta WHERE key='competitions_discovered'")
        except Exception:
            pass

        # Add season_id to torneos (migration)
        try:
            conn.execute("ALTER TABLE torneos ADD COLUMN season_id TEXT NOT NULL DEFAULT '2526'")
        except Exception:
            pass  # already exists

        # Add score columns to matches if they don't exist yet (migration)
        for col_def in ("score_home INTEGER", "score_away INTEGER"):
            try:
                conn.execute(f"ALTER TABLE matches ADD COLUMN {col_def}")
            except Exception:
                pass  # already exists

        # Add season_id to referees_catalog (migration)
        try:
            conn.execute("ALTER TABLE referees_catalog ADD COLUMN season_id TEXT DEFAULT '2526'")
        except Exception:
            pass
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_name_season "
                "ON referees_catalog(raw_name, season_id)"
            )
        except Exception:
            pass

        # Add rank columns to nomination_scores if they don't exist yet (migration)
        for col_def in ("rank_home INTEGER", "rank_away INTEGER", "n_teams INTEGER"):
            try:
                conn.execute(f"ALTER TABLE nomination_scores ADD COLUMN {col_def}")
            except Exception:
                pass  # already exists

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            -- One row per competition phase (torneo)
            CREATE TABLE IF NOT EXISTS torneos (
                torneo_id        INTEGER PRIMARY KEY,
                cat_id           INTEGER,
                comp_id          INTEGER,
                categoria_name   TEXT,
                competicion_name TEXT,
                torneo_name      TEXT,
                jornadas_discovered INTEGER DEFAULT 0
            );

            -- One row per (torneo, jornada) pair; jornada_num=0 means no jornada param
            CREATE TABLE IF NOT EXISTS jornadas (
                torneo_id   INTEGER,
                jornada_num INTEGER,
                scraped     INTEGER DEFAULT 0,
                PRIMARY KEY (torneo_id, jornada_num)
            );

            -- One row per match
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
                scraped_at      TEXT
            );

            -- Flat referee data per match
            CREATE TABLE IF NOT EXISTS referees (
                match_id       INTEGER PRIMARY KEY,
                referee_1      TEXT,
                referee_2      TEXT,
                scorekeeper_1  TEXT,
                scorekeeper_2  TEXT,
                table_delegate TEXT,
                tv             TEXT
            );
        """)


# --- meta ---

def is_discovery_done(season: str = config.SEASON_ID) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?",
            (f"competitions_discovered_{season}",),
        ).fetchone()
        return row is not None and row["value"] == "1"


def mark_discovery_done(season: str = config.SEASON_ID) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
            (f"competitions_discovered_{season}", "1"),
        )


# --- torneos ---

def upsert_torneo(d: dict) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO torneos(torneo_id, cat_id, comp_id, categoria_name,
                                competicion_name, torneo_name, season_id)
            VALUES(:torneo_id, :cat_id, :comp_id, :categoria_name,
                   :competicion_name, :torneo_name, :season_id)
            ON CONFLICT(torneo_id) DO UPDATE SET
                cat_id=excluded.cat_id,
                comp_id=excluded.comp_id,
                categoria_name=excluded.categoria_name,
                competicion_name=excluded.competicion_name,
                torneo_name=excluded.torneo_name,
                season_id=excluded.season_id
            """,
            d,
        )


def mark_torneo_jornadas_discovered(torneo_id: int) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            "UPDATE torneos SET jornadas_discovered=1 WHERE torneo_id=?",
            (torneo_id,),
        )


def get_torneos_needing_jornada_discovery() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM torneos WHERE jornadas_discovered=0"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_torneos() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM torneos").fetchall()]


# --- jornadas ---

def upsert_jornadas_batch(torneo_id: int, jornada_nums: list[int]) -> None:
    with _write_lock, _conn() as conn:
        conn.executemany(
            "INSERT INTO jornadas(torneo_id, jornada_num) VALUES(?,?) ON CONFLICT DO NOTHING",
            [(torneo_id, n) for n in jornada_nums],
        )


def mark_jornada_scraped(torneo_id: int, jornada_num: int) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            "UPDATE jornadas SET scraped=1 WHERE torneo_id=? AND jornada_num=?",
            (torneo_id, jornada_num),
        )


def get_jornadas_needing_scrape() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT j.torneo_id, j.jornada_num,
                   t.cat_id, t.comp_id, t.categoria_name, t.competicion_name, t.torneo_name
            FROM jornadas j
            JOIN torneos t ON t.torneo_id = j.torneo_id
            WHERE j.scraped = 0
            """
        ).fetchall()
        return [dict(r) for r in rows]


# --- matches ---

def upsert_matches_batch(matches: list[dict]) -> None:
    if not matches:
        return
    with _write_lock, _conn() as conn:
        conn.executemany(
            """
            INSERT INTO matches(match_id, torneo_id, home_team, away_team,
                                date, time, venue, status, score_home, score_away)
            VALUES(:match_id, :torneo_id, :home_team, :away_team,
                   :date, :time, :venue, :status, :score_home, :score_away)
            ON CONFLICT(match_id) DO UPDATE SET
                status=excluded.status,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                date=excluded.date,
                time=excluded.time,
                venue=excluded.venue,
                score_home=COALESCE(excluded.score_home, matches.score_home),
                score_away=COALESCE(excluded.score_away, matches.score_away)
            """,
            matches,
        )


def reset_jornadas_for_scores() -> int:
    """Mark all jornadas as unscraped so scores get picked up on next run."""
    with _write_lock, _conn() as conn:
        cur = conn.execute("UPDATE jornadas SET scraped=0")
        return cur.rowcount


def mark_referee_scraped(match_id: int, status: str) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            "UPDATE matches SET referee_scraped=1, scraped_at=?, status=? WHERE match_id=?",
            (datetime.utcnow().isoformat(), status, match_id),
        )


def get_matches_needing_referee_scrape() -> list[dict]:
    today = date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM matches
            WHERE referee_scraped = 0
               OR (
                    referee_scraped = 1
                    AND status = 'Pendiente'
                    AND date < ?
                  )
            """,
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- referees ---

def upsert_referees(match_id: int, d: dict) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            """
            INSERT INTO referees(
                match_id, referee_1, referee_2,
                scorekeeper_1, scorekeeper_2, table_delegate, tv
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET
                referee_1=excluded.referee_1,
                referee_2=excluded.referee_2,
                scorekeeper_1=excluded.scorekeeper_1,
                scorekeeper_2=excluded.scorekeeper_2,
                table_delegate=excluded.table_delegate,
                tv=excluded.tv
            """,
            (
                match_id,
                d.get("referee_1", ""),
                d.get("referee_2", ""),
                d.get("scorekeeper_1", ""),
                d.get("scorekeeper_2", ""),
                d.get("table_delegate", ""),
                d.get("tv", ""),
            ),
        )


# --- export ---

def export_json(output_path: str) -> int:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT
                m.match_id,
                t.competicion_name  AS competition,
                t.categoria_name    AS categoria,
                t.torneo_name       AS phase,
                m.home_team,
                m.away_team,
                m.date,
                m.time,
                m.venue,
                m.status,
                COALESCE(r.referee_1,      '') AS referee_1,
                COALESCE(r.referee_2,      '') AS referee_2,
                COALESCE(r.scorekeeper_1,  '') AS scorekeeper_1,
                COALESCE(r.scorekeeper_2,  '') AS scorekeeper_2,
                COALESCE(r.table_delegate, '') AS table_delegate,
                COALESCE(r.tv,             '') AS tv
            FROM matches m
            JOIN torneos t ON t.torneo_id = m.torneo_id
            LEFT JOIN referees r ON r.match_id = m.match_id
            ORDER BY m.date, m.time, m.match_id
            """
        ).fetchall()

    records = [dict(r) for r in rows]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return len(records)


# --- referee catalog ---

def upsert_catalog_entries(entries: list[dict]) -> None:
    with _write_lock, _conn() as conn:
        conn.executemany(
            """
            INSERT INTO referees_catalog(raw_name, normalized, category, territory, active, season_id)
            VALUES(:raw_name, :normalized, :category, :territory, :active, :season_id)
            ON CONFLICT DO NOTHING
            """,
            entries,
        )


def get_catalog(season_id: str | None = None) -> list[dict]:
    with _conn() as conn:
        if season_id:
            rows = conn.execute(
                "SELECT * FROM referees_catalog WHERE season_id=?", (season_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM referees_catalog").fetchall()
        return [dict(r) for r in rows]


def get_all_referee_names() -> list[str]:
    """Return every unique name that appears as referee_1 or referee_2."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT referee_1 AS name FROM referees WHERE referee_1 != ''
            UNION
            SELECT DISTINCT referee_2      FROM referees WHERE referee_2 != ''
            """
        ).fetchall()
        return [r[0] for r in rows]


# --- standings helpers ---

def get_finalizado_matches_before(torneo_id: int, cutoff_date: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT home_team, away_team, score_home, score_away
            FROM matches
            WHERE torneo_id=? AND status='Finalizado'
              AND date < ?
              AND score_home IS NOT NULL AND score_away IS NOT NULL
            """,
            (torneo_id, cutoff_date),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_teams_in_torneo(torneo_id: int) -> set[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT home_team FROM matches WHERE torneo_id=?", (torneo_id,)
        ).fetchall()
        rows2 = conn.execute(
            "SELECT DISTINCT away_team FROM matches WHERE torneo_id=?", (torneo_id,)
        ).fetchall()
        return {r[0] for r in rows} | {r[0] for r in rows2}


def get_regular_season_torneos_for_category(
    categoria_name: str, season_id: str | None = None
) -> list[dict]:
    with _conn() as conn:
        if season_id:
            rows = conn.execute(
                """
                SELECT * FROM torneos
                WHERE categoria_name=? AND torneo_name LIKE 'LIGA REGULAR%'
                  AND season_id=?
                """,
                (categoria_name, season_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM torneos
                WHERE categoria_name=? AND torneo_name LIKE 'LIGA REGULAR%'
                """,
                (categoria_name,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_all_finalizado_matches_in_torneo(torneo_id: int) -> list[dict]:
    """All completed matches in a torneo regardless of date — for final-season standings."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT home_team, away_team, score_home, score_away
            FROM matches
            WHERE torneo_id=? AND status='Finalizado'
              AND score_home IS NOT NULL AND score_away IS NOT NULL
            """,
            (torneo_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- nomination scores ---

def upsert_nomination_scores(rows: list[dict]) -> None:
    if not rows:
        return
    with _write_lock, _conn() as conn:
        conn.executemany(
            """
            INSERT INTO nomination_scores(
                match_id, referee_name, catalog_id,
                competition_mod, match_quality, score_factor, nomination_score,
                rank_home, rank_away, n_teams
            ) VALUES(:match_id,:referee_name,:catalog_id,
                     :competition_mod,:match_quality,:score_factor,:nomination_score,
                     :rank_home,:rank_away,:n_teams)
            ON CONFLICT(match_id, referee_name) DO UPDATE SET
                catalog_id=excluded.catalog_id,
                competition_mod=excluded.competition_mod,
                match_quality=excluded.match_quality,
                score_factor=excluded.score_factor,
                nomination_score=excluded.nomination_score,
                rank_home=excluded.rank_home,
                rank_away=excluded.rank_away,
                n_teams=excluded.n_teams
            """,
            rows,
        )


def get_couple_rankings() -> list[dict]:
    """
    Aggregate nomination scores by referee pair (order-independent).
    Uses referee_1's score row per match to avoid double-counting (both
    referees share the same nomination_score for a given match).
    Returns one row per (ref_a, ref_b) couple, ordered by total_score desc.
    """
    with _conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                CASE WHEN r.referee_1 < r.referee_2
                     THEN r.referee_1 ELSE r.referee_2 END AS ref_a,
                CASE WHEN r.referee_1 < r.referee_2
                     THEN r.referee_2 ELSE r.referee_1 END AS ref_b,
                COUNT(*)                              AS games,
                ROUND(SUM(ns1.nomination_score), 3)  AS total_score,
                ROUND(AVG(ns1.nomination_score), 3)  AS avg_score,
                ROUND(MAX(ns1.nomination_score), 3)  AS best_score,
                MAX(m.date)                           AS last_game,
                COALESCE(rc_a.category, '?')          AS cat_a,
                COALESCE(rc_b.category, '?')          AS cat_b
            FROM referees r
            JOIN matches m ON m.match_id = r.match_id
            JOIN nomination_scores ns1
                ON ns1.match_id = r.match_id
               AND ns1.referee_name = r.referee_1
            LEFT JOIN nomination_scores ns2
                ON ns2.match_id = r.match_id
               AND ns2.referee_name = r.referee_2
            LEFT JOIN referees_catalog rc_a ON rc_a.id = ns1.catalog_id
            LEFT JOIN referees_catalog rc_b ON rc_b.id = ns2.catalog_id
            WHERE r.referee_1 != '' AND r.referee_2 != ''
              AND r.referee_1 IS NOT NULL AND r.referee_2 IS NOT NULL
            GROUP BY ref_a, ref_b
            ORDER BY total_score DESC
        """).fetchall()]


def get_referee_rankings() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                ns.referee_name,
                rc.category,
                rc.territory,
                COUNT(*)                          AS nominations,
                ROUND(SUM(ns.nomination_score),3) AS total_score,
                ROUND(AVG(ns.nomination_score),3) AS avg_score,
                ROUND(MAX(ns.nomination_score),3) AS best_score,
                ROUND(AVG(ns.competition_mod),3)  AS avg_competition_mod,
                ROUND(AVG(ns.match_quality),3)    AS avg_match_quality,
                ROUND(AVG(ns.score_factor),3)     AS avg_score_factor
            FROM nomination_scores ns
            LEFT JOIN referees_catalog rc ON rc.id = ns.catalog_id
            GROUP BY ns.referee_name
            ORDER BY total_score DESC
        """).fetchall()]


# --- stats ---

def print_stats() -> None:
    with _conn() as conn:
        n_torneos = conn.execute("SELECT COUNT(*) FROM torneos").fetchone()[0]
        n_jornadas = conn.execute("SELECT COUNT(*) FROM jornadas").fetchone()[0]
        n_jornadas_done = conn.execute("SELECT COUNT(*) FROM jornadas WHERE scraped=1").fetchone()[0]
        n_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        n_refs = conn.execute("SELECT COUNT(*) FROM matches WHERE referee_scraped=1").fetchone()[0]
        cats = conn.execute("SELECT DISTINCT categoria_name FROM torneos").fetchall()
    print(f"  Torneos: {n_torneos} | Jornadas: {n_jornadas_done}/{n_jornadas} scraped")
    print(f"  Matches: {n_matches} | Referee data: {n_refs}")
    print(f"  Categories: {[r[0] for r in cats]}")
