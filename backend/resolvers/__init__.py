import asyncio
import logging
from typing import Optional

from backend.resolvers.base import BaseResolver
from backend.resolvers.vidmoly import VidmolyResolver
from backend.resolvers.filesforever import FilesForeverResolver
from backend.resolvers.abyssplayer import AbyssPlayerResolver
from backend.resolvers.p2pplay import P2PPlayResolver


logger = logging.getLogger("anikoko.resolver")


_ALL_RESOLVERS: list[BaseResolver] = [
    VidmolyResolver(),
    FilesForeverResolver(),
    AbyssPlayerResolver(),
    P2PPlayResolver(),
]

# A single resolver shouldn't be able to stall an episode fetch. Most
# resolvers return in <2s; anything over this is either broken or in a
# redirect loop, and a missing source beats a stuck request.
RESOLVER_TIMEOUT = 12.0


def get_resolver(url: str) -> Optional[BaseResolver]:
    for r in _ALL_RESOLVERS:
        if r.matches(url):
            return r
    return None


def all_resolvers() -> list[BaseResolver]:
    return list(_ALL_RESOLVERS)


async def resolve_embed(url: str) -> Optional[str]:
    r = get_resolver(url)
    if not r:
        return None
    try:
        return await asyncio.wait_for(r.resolve(url), timeout=RESOLVER_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("resolver %s timed out on %s", r.name, url)
        return None
    except Exception as e:
        logger.warning("resolver %s failed on %s: %s", r.name, url, e, exc_info=True)
        return None