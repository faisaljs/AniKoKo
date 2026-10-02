from typing import Optional

from backend.resolvers.vidmoly import VidmolyResolver
from backend.resolvers.filesforever import FilesForeverResolver
from backend.resolvers.abyssplayer import AbyssPlayerResolver
from backend.resolvers.p2pplay import P2PPlayResolver


_ALL_RESOLVERS = [
    VidmolyResolver(),
    FilesForeverResolver(),
    AbyssPlayerResolver(),
    P2PPlayResolver(),
]


def get_resolver(url: str):
    for r in _ALL_RESOLVERS:
        if r.matches(url):
            return r
    return None


async def resolve_embed(url: str) -> Optional[str]:
    r = get_resolver(url)
    if not r:
        return None
    try:
        return await r.resolve(url)
    except Exception:
        return None