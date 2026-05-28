"""Parse referee plantilla PDFs → list of {raw_name, normalized, category, territory, active}."""

import re
import unicodedata

import pdfplumber

import config
import db


def _normalize(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace — used for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_str.lower().split())


# "Apellido1 Apellido2, Nombre" → "NOMBRE APELLIDO1 APELLIDO2" style canonical
def _canonical(raw: str) -> str:
    raw = raw.strip()
    if "," in raw:
        surnames, given = raw.split(",", 1)
        return f"{given.strip()} {surnames.strip()}"
    return raw


_NUMBERED = re.compile(r"^\d+\.\s+(.+)$")
_EXCEDENCIA = re.compile(r"\(EXCEDENCIA\)", re.IGNORECASE)


def parse_pdf(path: str, category: str) -> list[dict]:
    entries: list[dict] = []
    current_territory = ""

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Federation headers are all-caps lines without numbering
                # Heuristic: line is ALL CAPS, no leading digit, reasonably long
                if (
                    not _NUMBERED.match(line)
                    and line.isupper()
                    and len(line) > 10
                    and not line.startswith("REAL FEDERACION")
                    and not line.startswith("COMITÉ")
                    and not line.startswith("PLANTILLA")
                    and not line.startswith("DIVISIÓN")
                    and not line.startswith("PRIMERA")
                    and not any(c.isdigit() for c in line[:3])
                ):
                    current_territory = line.strip()
                    continue

                m = _NUMBERED.match(line)
                if not m:
                    continue

                raw = m.group(1).strip()
                active = 1
                if _EXCEDENCIA.search(raw):
                    active = 0
                    raw = _EXCEDENCIA.sub("", raw).strip()

                canonical = _canonical(raw)
                entries.append(
                    {
                        "raw_name": raw,
                        "normalized": _normalize(canonical),
                        "category": category,
                        "territory": current_territory,
                        "active": active,
                    }
                )

    return entries


def load_all_pdfs() -> int:
    """Parse all season PDFs from plantillas/ and insert into referees_catalog. Idempotent."""
    import os
    existing = {(e["raw_name"], e["season_id"]) for e in db.get_catalog()}
    total_new = 0
    for season_id in config.CATALOG_SEASONS:
        files = config.PDF_FILES.get(season_id, {})
        season_entries: list[dict] = []
        for category, filename in files.items():
            if not os.path.exists(filename):
                continue
            entries = parse_pdf(filename, category)
            for e in entries:
                e["season_id"] = season_id
            season_entries.extend(entries)
        new_entries = [e for e in season_entries if (e["raw_name"], season_id) not in existing]
        if new_entries:
            db.upsert_catalog_entries(new_entries)
            total_new += len(new_entries)
        if season_entries:
            print(f"  [{season_id}] {len(season_entries)} referees ({len(new_entries)} new)")
    return total_new
