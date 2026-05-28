import asyncio

import aiohttp

import config
import db
import scraper
import pdf_parser
import scoring


async def main() -> None:
    db.init_db()

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
    connector = aiohttp.TCPConnector(limit=config.MAX_CONCURRENT)

    async with aiohttp.ClientSession(
        headers=config.HEADERS,
        connector=connector,
    ) as session:

        # Phase 0: previous season — discover and scrape everything
        if not db.is_discovery_done(config.PREV_SEASON_ID):
            await scraper.discover_competitions(session, semaphore, season_id=config.PREV_SEASON_ID)
        else:
            print(f"Phase 0 [{config.PREV_SEASON_ID}]: skipped (already discovered)")

        # Phase 1: current season — discover all torneos for target categories
        if not db.is_discovery_done(config.SEASON_ID):
            await scraper.discover_competitions(session, semaphore, season_id=config.SEASON_ID)
        else:
            torneos = db.get_all_torneos()
            print(f"Phase 1 [{config.SEASON_ID}]: skipped ({len(torneos)} torneos in DB)")

        # Phase 2a: discover jornadas per torneo
        await scraper.discover_jornadas(session, semaphore)

        # Phase 2b: collect matches + scores
        await scraper.collect_matches(session, semaphore)

        # Phase 3: fetch referee nominations
        await scraper.fetch_referees(session, semaphore)

    count = db.export_json(config.OUTPUT_PATH)
    print(f"\nDone. {count} matches written to {config.OUTPUT_PATH}")
    db.print_stats()

    # Phase 4: parse PDF referee catalogs
    print("\nPhase 4: Parsing referee PDFs...")
    n_refs = pdf_parser.load_all_pdfs()
    print(f"  {n_refs} referees loaded from PDFs")

    # Phase 5: compute nomination scores
    print("\nPhase 5: Computing nomination scores...")
    n_scores = scoring.compute_all_scores()
    print(f"  {n_scores} nomination scores computed")

    # Print quick match stats
    catalog = db.get_catalog()
    rankings = db.get_referee_rankings()
    print(f"\nReferee catalog: {len(catalog)} entries")
    print(f"Referee rankings: {len(rankings)} unique referees scored")
    if rankings:
        print(f"  Top 5 by total score:")
        for r in rankings[:5]:
            cat = r.get("category") or "?"
            print(f"    [{cat:8s}] {r['referee_name']:<35s} "
                  f"total={r['total_score']:6.3f}  "
                  f"n={r['nominations']:3d}  "
                  f"avg={r['avg_score']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
