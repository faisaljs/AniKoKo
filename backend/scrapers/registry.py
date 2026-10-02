from typing import Dict, List

from backend.scrapers.desidubanime import DesiDubAnimeScraper
from backend.scrapers.base import BaseScraper


_SCRAPERS: Dict[str, BaseScraper] = {
    "desidubanime": DesiDubAnimeScraper(),
}


def all_scrapers() -> List[BaseScraper]:
    return list(_SCRAPERS.values())


def get_scraper(slug: str) -> BaseScraper:
    return _SCRAPERS[slug]


def slugs() -> List[str]:
    return list(_SCRAPERS.keys())