BASE_URL = "https://resultadosbalonmano.isquad.es"
SEASON_ID      = "2526"
PREV_SEASON_ID = "2425"
TERRITORIAL_ID = "9999"
SURFACE_ID = "1"
AMBITO_NATIONAL = "0"
DB_PATH = "handball.db"
OUTPUT_PATH = "output/referees.json"

MAX_CONCURRENT = 20

# Exact names from the <select id='categorias'> dropdown
TARGET_CATEGORIES = {
    "CAMPEONATO ESTATAL DE DIVISION DE HONOR ELITE FEMENINA",
    "CAMPEONATO ESTATAL DE DIVISION DE HONOR MASCULINA",
    "CAMPEONATO ESTATAL DE DIVISION DE HONOR PLATA MASCULINA",
    "CAMPEONATO ESTATAL DE DIVISION DE HONOR ORO FEMENINA",
    "CAMPEONATO ESTATAL DE PRIMERA DIVISION MASCULINA",
    "CAMPEONATO ESTATAL DE DIVISION DE HONOR PLATA FEMENINA",
}

# ── Scoring ──────────────────────────────────────────────────────────────────

# Weeks before match date to use for standings snapshot
STANDINGS_LAG_DAYS = 21

# Gender multiplier: women's competitions relative to men's
WOMEN_MULTIPLIER = 0.75

# Tier modifier: competition prestige level (checked in order, first match wins)
# Applied on top of gender and phase multipliers
TIER_MODIFIERS: list[tuple[str, float]] = [
    ("PRIMERA DIVISION", 0.65),   # Primera Nacional — same tier as Oro
    ("ORO",              0.65),   # D.H. Oro Femenina — same tier as Primera
    ("PLATA",            0.45),   # D.H. Plata (both genders) — below the two above
    # Default → 1.00  (top: ASOBAL, Liga Guerreras Iberdrola)
]

# Phase multipliers keyed by keyword (checked in order — most specific first)
PHASE_MULTIPLIERS: list[tuple[str, float]] = [
    ("CUARTOS",                 1.30),
    ("SEMIFINAL",               1.50),
    ("GRUPO DE ASCENSO",        1.20),
    ("PLAY-OFF DE ASCENSO",     1.20),
    ("2ª FASE",                 1.20),
    ("PLAY-DOWN",               1.10),
    ("PLAY-OFF DE PERMANENCIA", 1.10),
    ("TERCERA ELIMINATORIA",    1.50),
    ("SEGUNDA ELIMINATORIA",    1.30),
    ("SEGUNDA FASE",            1.30),
    ("PRIMERA ELIMINATORIA",    1.10),
    ("PRIMERA FASE",            1.10),
    ("FASE UNICA",              1.80),  # Supercopa / Copa de España
    ("FINAL",                   2.00),  # catches FINAL-UNICO and FASE FINAL-unico
]

# Normalised goal margin denominator for score_factor = 1/(1 + goal_diff/MARGIN_NORM)
MARGIN_NORM = 5.0

# PDF category labels (must match text in PDFs)
PDF_CATEGORIES = {
    "División de Honor Élite":   "elite",
    "División de Honor":         "honor",
    "Primera División":          "primera",
}

# Ordered newest → oldest; used to enumerate consecutive season transitions
CATALOG_SEASONS = ["2526", "2425", "2324", "2223", "2122", "2021", "1920", "1819", "1718"]

PDF_FILES = {
    "2526": {
        "elite":   "plantillas/Division-de-Honor-Elite-2025-2026.pdf",
        "honor":   "plantillas/Division-de-Honor-Plata-2025-2026.pdf",
        "primera": "plantillas/Primera-Nacional-2025-2026.pdf",
    },
    "2425": {
        "elite":   "plantillas/DH-ELITE-24_25.pdf",
        "honor":   "plantillas/DIV-HONOR-PLATA-24_25.pdf",
        "primera": "plantillas/1NACIONAL-24_25.pdf",
    },
    "2324": {
        "elite":   "plantillas/Plantilla-arbitral-DHE-23-24.pdf",
        "honor":   "plantillas/Plantilla-arbitral-DHB-23-24.pdf",
        "primera": "plantillas/Plantilla-arbitral-1NAC-23-24.pdf",
    },
    "2223": {
        "elite":   "plantillas/Plantilla-arbitral-DHE-22-23.pdf",
        "honor":   "plantillas/Plantilla-arbitral-DHB-22-23.pdf",
        "primera": "plantillas/Plantilla-arbitral-1NAC-22-23.pdf",
    },
    "2122": {
        "elite":   "plantillas/Plantilla-arbitral-DHE-21-22.pdf",
        "honor":   "plantillas/Plantilla-arbitral-DHB-21-22.pdf",
        "primera": "plantillas/Plantilla-arbitral-1NAC-21-22.pdf",
    },
    "2021": {
        "elite":   "plantillas/Plantilla-arbitral-DHE-20-21.pdf",
        "honor":   "plantillas/Plantilla-arbitral-DHB-20-21.pdf",
        "primera": "plantillas/Plantilla-arbitral-1NAC-20-21.pdf",
    },
    "1920": {
        "elite":   "plantillas/Plantilla-arbitral-Division-de-Honor-Elite-19_20.pdf",
        "honor":   "plantillas/Plantilla-arbitral-Division-de-Honor-Plata-19_20.pdf",
        "primera": "plantillas/Plantilla-arbitral-Primera-Division-19_20.pdf",
    },
    "1819": {
        "elite":   "plantillas/DIV-HONOR-ELITE-18-19.pdf",
        "honor":   "plantillas/DIV-HONOR-PLATA-18-19.pdf",
        "primera": "plantillas/1NACIONAL-18-19.pdf",
    },
    "1718": {
        "elite":   "plantillas/Plantilla-arbitral-Division-de-Honor-Elite-17_18.pdf",
        "honor":   "plantillas/Plantilla-arbitral-Division-de-Honor-Plata-17_18.pdf",
        "primera": "plantillas/Plantilla-arbitral-Primera-Division-17_18.pdf",
    },
}

# Fuzzy-match threshold (0–100); names scoring below this are not linked
MATCH_THRESHOLD = 80

# Cross-season name aliases: maps normalized variant → normalized canonical.
# Add entries here when the automatic matching links the wrong people, or misses
# an obvious same-person pair (e.g. extra middle name that drops the score below threshold).
# Keys and values should be the plain lowercase accent-stripped forms.
MANUAL_CROSS_ALIASES: dict[str, str] = {
    # Extra middle name in 2017/18 PDF vs later seasons
    # "luis ignacio colmenero guillen" handled automatically via token_set_ratio fallback
}

# Manual catalog ID overrides for names that fall below the fuzzy threshold.
# Keys are the exact scraped referee names from the DB.
MANUAL_ALIASES: dict[str, int] = {
    "YONATAN LAZARO VILLEGAS":      142,  # Lázaro Villegas, Jonathan (different given-name spelling)
    "FRANCISCO JOSE MARTINEZ HITA": 202,  # Martínez Hita, José (extra given name in scraped data)
    "JORGE OTO GAÑEZ":              110,  # Oto Gañez, Jorge
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
