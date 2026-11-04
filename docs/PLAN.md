# Plan: centralized handball game statistics

Goal: turn this repo from a Spanish-referee tracker into the single place where
every professional game we care about is stored with **who was involved**
(teams, players, staff, referees, delegates), **what happened** (every
individual action, with clock and running score) and **the result** (final
and per-period score), so any statistical analysis can be run from one database.

## Scope

| Country | Competition | Level | Source |
|---|---|---|---|
| FR | Liqui Moly StarLigue (LNH D1) | men, tier 1 | S3 archive, then FFHB match-sheet server |
| FR | ProLigue (LNH D2) | men, tier 2 | S3 archive, then FFHB match-sheet server |
| FR | Ligue Butagaz Énergie (D1F) | women, tier 1 | S3 archive, then FFHB match-sheet server |
| ES | Liga ASOBAL (DH Masculina) | men, tier 1 | RFEBM results platform (isquad) |
| ES | Liga Guerreras Iberdrola (DH Élite / DH Femenina) | women, tier 1 | RFEBM results platform (isquad) |

Volume: about 1,100 games per season across the five leagues, with about 300
recorded actions per game, so roughly 350k event rows per season. SQLite holds
that easily, so we keep it (see "Storage" below).

## Where the repo is today

- `scraper.py` discovers competitions, rounds and matches on
  `resultadosbalonmano.isquad.es` (the RFEBM results backend) and scrapes
  **referees only** from `previo.php`.
- `db.py` and `alembic/` hold a SQLite schema (`torneos`, `jornadas`, `matches`,
  `referees`, `referees_catalog`, `nomination_scores`) keyed by isquad IDs.
- `api/` and `static/` serve a FastAPI dashboard of referee stats.
- Nothing handles French data, players, events or S3 yet.

Spain discovery already works, so the Spanish half of this plan mostly means
adding a parser for the match report and narrowing the categories.

## Target architecture

```
handball/
  sources/            # fetch raw documents and touch nothing else
    s3_archive.py     # list/download objects from the bucket
    ffhb.py           # discover FR games and download match sheets (PDF)
    isquad.py         # existing discovery code, moved here and extended to actas
  parsers/            # raw document -> normalized GameRecord (pure functions)
    ffhb_sheet.py     # FFHB/FDME "feuille de match" PDF
    isquad_acta.py    # RFEBM acta / play-by-play HTML
  model.py            # GameRecord, Person, Event dataclasses (one shape for all sources)
  load.py             # GameRecord -> DB (idempotent upserts)
  identity.py         # person/team resolution across sources (reuses name_matcher.py)
  cli.py              # `uv run hb ...` entry points
```

Core rule: **store raw first, parse second.** Every fetched document is
recorded in `source_documents` (source, URL or S3 key, sha256, fetched_at,
parser_version, parse_status). That lets us re-parse everything after a
parser fix without re-scraping, and makes every run idempotent and resumable.
New French reports we scrape are uploaded to the same S3 bucket, so the bucket
stays the complete raw archive.

## Data model (new Alembic migration `003_games`)

- `competitions`: id, country, name, gender, tier, source.
- `seasons`: id, label (`2025-26`).
- `teams`: id, canonical name, country; `team_aliases` (source, raw name).
- `persons`: id, full name, birth year (if known), gender; `person_ids`
  (source, external id such as an FFHB licence or RFEBM licence number).
- `games`: id, competition_id, season_id, round, date and time, venue,
  home_team_id, away_team_id, score_home, score_away, ht_home, ht_away,
  status, source, source_game_id. Unique on (source, source_game_id).
- `game_participants`: game_id, person_id, team side (or `null` for
  officials), role (`player`, `goalkeeper`, `staff`, `referee`, `delegate`,
  `timekeeper`, `scorekeeper`), shirt number, captain flag.
- `game_events`: game_id, seq, period, clock_seconds, team side, person_id,
  type, running score home and away, raw text. Types: `goal`, `goal_7m`,
  `miss_7m`, `save_7m`, `warning`, `two_min`, `red`, `blue`, `timeout`,
  `period_start` and `period_end`, plus `shot_miss` and `save` when the source has them.
- `player_game_totals`: a view (or materialized table) of goals, shots, 7m,
  warnings, suspensions and disqualifications per player per game. It is
  derived from events and cross-checked against the totals box printed on
  the match sheet.
- `source_documents`: as described above.

The existing referee tables keep working for now. In phase 5 the
dashboard is pointed at `games` and `game_participants`, then the old
tables are dropped.

## Phases

### Phase 0: unblock access and check the sources (first, short)
1. Get the S3 bucket name, region and prefix layout, plus working
   credentials. The AWS keys currently in the cloud environment are rejected
   (`InvalidAccessKeyId`).
2. Allow outbound access to `*.ffhandball.fr`, `lnh.fr`,
   `ligue-feminine-handball.fr`, `rfebm.com`,
   `resultadosbalonmano.isquad.es` and the S3 endpoint in the environment's
   network settings. All of them are currently blocked from the cloud container.
3. Sample about 20 reports from S3 across seasons and leagues: file type
   (PDF? FDME export?), naming scheme, and which fields they contain.
4. Fetch one current match sheet per league from the FFHB match-sheet server
   (`media-ffhb-fdm.ffhandball.fr`) and confirm that it covers
   StarLigue and ProLigue too, not just the LFH and amateur levels. If it
   doesn't, fall back to the LNH match-centre pages for those two leagues.
5. Find the isquad page that carries the Spanish acta or play-by-play
   (look at the links from `previo.php` and the match page) and save fixtures.

Deliverable: `tests/fixtures/` with real sample documents, plus a short note in
this file confirming the endpoints.

### Phase 1: schema and loader
- Add `handball/model.py` and the `003_games` migration, plus `load.py`
  with idempotent upserts keyed on (source, source_game_id).
- Add `identity.py`: match on external licence ID first, then fall back to
  fuzzy name plus team plus season using the existing `name_matcher.py` /
  rapidfuzz logic. Ambiguous matches are logged to a review table,
  never auto-merged.
- Tests: load a hand-written GameRecord twice and get the same rows.

### Phase 2: S3 backfill (France, historical)
- `hb s3 sync`: list the bucket, register each object in `source_documents`
  (key plus ETag means no re-download), and download to a local cache.
- `parsers/ffhb_sheet.py` with pdfplumber, which is already a dependency: header
  (competition, date, venue, teams), rosters with licence numbers,
  officials, the chronological event table, and period scores. Keep a
  `parser_version` so we can re-parse with `hb reparse`.
- Validate each game: the sum of goal events must equal the final score, and
  per-player totals must match the sheet's totals box. Failures are marked
  `parse_status='invalid'` with the reason instead of being loaded silently.
- Filter to the three professional leagues on load. The other S3 reports stay
  registered but unparsed.
- Deliverable: a per-league, per-season coverage report (`hb coverage`).

### Phase 3: France catch-up scraper
- For each league, the cut-off is `max(games.date)`, taken from data loaded from
  S3, so we only scrape after the latest game we already have.
- `sources/ffhb.py`: walk the competition calendar from the cut-off to today,
  pick finished games, download the match sheet, and **upload it to S3 under the
  existing key scheme**. The same parser and loader as phase 2 then handle it.
- Be polite: rate limiting, retries with backoff, and a clear User-Agent. Match
  sheets are published the day after the game, so missing sheets are
  retried on later runs rather than treated as failures.

### Phase 4: Spain (ASOBAL and Guerreras)
- Move the discovery code from `scraper.py` to `sources/isquad.py`. Set
  `TARGET_CATEGORIES` to the top men's and women's levels only, with the
  per-season name variants already listed in `config.py`.
- Extend the existing referee step with `parsers/isquad_acta.py`: rosters,
  officials (this replaces the current `previo.php` referee scrape), events and
  score. Run the same validation as France.
- Backfill every season isquad exposes (`id_temp`), then keep it incremental.

### Phase 5: one analysis surface
- Move the existing referee dashboard queries (`api/queries.py`) onto the
  new tables, so referee stats cover France as well.
- Add API endpoints and tabs for games, players and teams (box scores,
  scorer leaderboards, 7m conversion, discipline per referee pair, home and away
  splits, comebacks from the running score).
- Add `notebooks/` or `analysis/` for ad-hoc work against the same DB.

### Phase 6: keep it fresh
- `hb update` = France catch-up + Spain incremental + reparse of any
  invalid documents. Run it nightly as a GitHub Action or scheduled task.
  Back up the DB to S3 as a snapshot instead of committing `handball.db`
  (11 MB and growing) to git.

## Storage

Stay on SQLite. The volume is small and the existing stack uses it. If the
dashboard later needs to be shared or written by several jobs at once,
the schema is plain SQL and can move to Postgres (for example Neon).

## Open questions for you

1. **S3:** what is the bucket name, region and prefix, and can you provide
   working read and write credentials? Write access is needed to archive new reports.
2. **Report format in S3:** are they FFHB PDFs, FDME exports or something
   else? Do they include StarLigue and ProLigue, or only federation-run games?
3. **History depth:** which seasons should be in scope for each league? All of S3,
   and all seasons isquad exposes for Spain?
4. **Spanish women:** is "División de Honor femenina" the current top
   tier, DH Élite / Liga Guerreras Iberdrola? I assume yes.
5. **Game types:** I assume regular season plus playoffs for every league.
   Should cup competitions (Coupe de France, Copa del Rey, Copa de la Reina)
   or European games ever be in scope?
