"""Detect gender from Spanish first names. Returns (gender, confidence)."""

import unicodedata


def _norm(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


_MASCULINE_RAW: dict[str, float] = {
    # Spanish
    "aaron": 1.0, "abel": 1.0, "adrian": 1.0, "agustin": 1.0, "alberto": 1.0,
    "alejandro": 1.0, "alfonso": 1.0, "alfredo": 1.0, "alvaro": 1.0, "andres": 1.0,
    "angel": 1.0, "anibal": 1.0, "antonio": 1.0, "armando": 1.0, "arturo": 1.0,
    "axel": 1.0, "bernardino": 1.0, "carlos": 1.0, "cesar": 1.0, "christian": 1.0,
    "cristian": 1.0, "daniel": 1.0, "dario": 1.0, "david": 1.0, "diego": 1.0,
    "eduardo": 1.0, "efren": 1.0, "elias": 1.0, "emilio": 1.0, "enrique": 1.0,
    "eric": 1.0, "erik": 1.0, "ernesto": 1.0, "fernando": 1.0, "francisco": 1.0,
    "gabriel": 1.0, "gaspar": 1.0, "gerardo": 1.0, "gonzalo": 1.0, "gregorio": 1.0,
    "guillermo": 1.0, "hector": 1.0, "ignacio": 1.0, "ivan": 1.0, "javier": 1.0,
    "jesus": 1.0, "jhonny": 1.0, "jonathan": 1.0, "jorge": 1.0, "jose": 1.0,
    "juan": 1.0, "julio": 1.0, "kevin": 1.0, "leandro": 1.0, "leonardo": 1.0,
    "lucas": 1.0, "luis": 1.0, "manuel": 1.0, "marcos": 1.0, "mario": 1.0,
    "martin": 1.0, "matias": 1.0, "mauro": 1.0, "miguel": 1.0, "nicolas": 1.0,
    "omar": 1.0, "oscar": 1.0, "pablo": 1.0, "pedro": 1.0, "rafael": 1.0,
    "ramon": 1.0, "raul": 1.0, "roberto": 1.0, "rodrigo": 1.0, "ruben": 1.0,
    "samuel": 1.0, "santiago": 1.0, "saul": 1.0, "sebastian": 1.0, "sergio": 1.0,
    "tomas": 1.0, "vicente": 1.0, "victor": 1.0,
    # Catalan
    "albert": 1.0, "andreu": 1.0, "arnau": 1.0, "bernat": 1.0, "damia": 1.0,
    "enric": 1.0, "joan": 1.0, "jordi": 1.0, "josep": 1.0, "lluis": 1.0,
    "marc": 1.0, "miquel": 1.0, "oriol": 1.0, "pau": 1.0, "pere": 1.0,
    "rafel": 1.0, "sergi": 1.0, "guillem": 1.0, "gillem": 1.0, "gillen": 1.0,
    "roland": 1.0,
    # Basque
    "aimar": 1.0, "aitor": 1.0, "andoni": 1.0, "aritz": 1.0, "arkaitz": 1.0,
    "eder": 1.0, "ekain": 1.0, "endika": 1.0, "igor": 1.0, "iker": 1.0,
    "inaki": 1.0, "inigo": 1.0, "ion": 1.0, "jon": 1.0, "joseba": 1.0,
    "josu": 1.0, "lain": 1.0, "markel": 1.0, "mikel": 1.0, "unai": 1.0,
    "xabier": 1.0,
    # Spanish additional
    "fermin": 1.0, "millan": 1.0, "fco": 1.0,
    # Foreign / unusual but definitively M in Spain
    "goyo": 1.0, "samer": 1.0, "soufiane": 1.0, "styk": 1.0,
    "vlad": 0.9, "wassem": 0.9, "alex": 0.9, "jordan": 0.9,
}

_FEMININE_RAW: dict[str, float] = {
    # Spanish
    "alba": 1.0, "alicia": 1.0, "amaia": 1.0, "amparo": 1.0, "ana": 1.0,
    "andrea": 0.9, "angeles": 1.0, "ariana": 1.0, "beatriz": 1.0, "carla": 1.0,
    "carmen": 1.0, "celia": 1.0, "concepcion": 1.0, "cristina": 1.0,
    "desire": 1.0, "desiree": 1.0, "dolores": 1.0, "elena": 1.0, "esther": 1.0,
    "eva": 1.0, "fernanda": 1.0, "gabriela": 1.0, "gloria": 1.0,
    "ines": 1.0, "irene": 1.0, "isabel": 1.0, "lara": 1.0, "laura": 1.0,
    "leyre": 1.0, "libertad": 1.0, "lidia": 1.0, "lorena": 1.0, "lucia": 1.0,
    "maite": 1.0, "maialen": 1.0, "maria": 1.0, "marta": 1.0, "mayte": 1.0,
    "mercedes": 1.0, "miriam": 1.0, "monica": 1.0, "montserrat": 1.0,
    "nuria": 1.0, "noelia": 1.0, "ona": 1.0, "patricia": 1.0, "paula": 1.0,
    "pilar": 1.0, "raquel": 1.0, "rebeca": 1.0, "rosa": 1.0, "rocio": 1.0,
    "sara": 1.0, "sandra": 1.0, "silvia": 1.0, "sonia": 1.0, "soraya": 1.0,
    "susana": 1.0, "tamara": 1.0, "tania": 1.0, "teresa": 1.0, "vanessa": 1.0,
    "veronica": 1.0, "yolanda": 1.0,
    # Catalan / Basque feminine
    "ane": 1.0, "edurne": 1.0, "itziar": 1.0, "laia": 1.0, "leire": 1.0,
    "meritxell": 1.0, "mireia": 1.0, "neus": 1.0, "nerea": 1.0, "olga": 1.0,
    "garbine": 1.0,
    # Foreign feminine
    "ioana": 1.0, "kalina": 1.0,
}

_MASCULINE: dict[str, float] = {_norm(k): v for k, v in _MASCULINE_RAW.items()}
_FEMININE:  dict[str, float] = {_norm(k): v for k, v in _FEMININE_RAW.items()}


def detect(raw_name: str) -> tuple[str, float]:
    """
    Given a raw catalog name ("Surname(s), Given Name(s)" or "Given Surnames"),
    return (gender, confidence) where gender is 'M', 'F', or '' (unknown).

    Strategy:
    1. Split on the first comma to isolate given names (handles "Surname, Given").
    2. Scan every word in the given-name portion, skipping single-char abbreviations.
    3. Return the first word that matches the definitive dictionary.
    4. If no dictionary match, apply a suffix heuristic to the first non-abbreviation word.
    This handles compound names, abbreviated first initials, and mis-formatted entries.
    """
    raw = raw_name.strip()
    if "," in raw:
        _, given = raw.split(",", 1)
        words = given.strip().split()
    else:
        words = raw.strip().split()

    if not words:
        return "", 0.0

    # Strip trailing punctuation from each word (e.g. "Carlos." → "Carlos")
    cleaned = [_norm(w.rstrip(".")) for w in words]

    # First pass: definitive dictionary lookup — scan all words, skip abbreviations
    for w in cleaned:
        if len(w) <= 2:
            continue
        if w in _MASCULINE:
            return "M", _MASCULINE[w]
        if w in _FEMININE:
            return "F", _FEMININE[w]

    # Second pass: suffix heuristic on first non-abbreviation word only
    for w in cleaned:
        if len(w) <= 2:
            continue
        if w.endswith("a") and not w.endswith("ba"):
            return "F", 0.6
        if w.endswith("o"):
            return "M", 0.6
        break

    return "", 0.0
