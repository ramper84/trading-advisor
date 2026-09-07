"""Scheduled-refresh loop, per source cadence in data_catalog.yaml
(Phase 9) — not built yet. This placeholder only proves the container
starts cleanly and can see the catalog; it does no fetching yet.
"""

import logging
import time

from app.ingest.catalog import load_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    catalog = load_catalog()
    logger.info(
        "refresh_worker placeholder started — %d source(s) configured, not yet fetching (Phase 9): %s",
        len(catalog.included_sources()),
        [s.name for s in catalog.included_sources()],
    )
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
