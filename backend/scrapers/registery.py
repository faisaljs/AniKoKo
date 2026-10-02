from typing import Dict, List

from scrapers.animedubhindi import AnimeDubHindiScraper
from backend.scrapers.desidubanime import DesiDubAnimeScraper
from scrapers.toonworld4all import ToonWorld4AllScraper
from backend.scrapers.base import BaseScraper


_SCRAPERS: Dict[str, BaseScraper] = {
    "animedubhindi": AnimeDubHindiScraper(),
    "desidubanime": DesiDubAnimeScraper(),
    "toonworld4all": ToonWorld4AllScraper(),
}


def all_scrapers() -> List[BaseScraper]:
    return list(_SCRAPERS.values())


def get_scraper(slug: str) -> BaseScraper:
    return _SCRAPERS[slug]


def slugs() -> List[str]:
    return list(_SCRAPERS.keys())