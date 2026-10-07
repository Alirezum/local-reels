"""Discovery weights for the reels feed.

Less-watched media scores higher so unseen clips surface first.
"""

from __future__ import annotations

import random

import aiosqlite

from .schemas import VideoOut
from .stats import SESSIONS_CTE

DEFAULT_WEIGHT = 1.0
SECONDS_PER_MINUTE = 60.0
WATCHED_MINUTES_DIVISOR = 5.0


async def fetch_view_weights(conn: aiosqlite.Connection) -> dict[str, float]:
    """Per-video discovery weight: less-watched -> higher weight.

    weight = 1 / (1 + view_sessions + watched_minutes / 5). Never-seen media
    score 1.0; a heavily watched clip scores near 0.
    """
    sql = (
        SESSIONS_CTE + "SELECT video_id, SUM(is_new_view) AS views, "
        "SUM(duration_watched) AS seconds FROM sessions GROUP BY video_id"
    )
    async with conn.execute(sql) as cur:
        rows = await cur.fetchall()
    return {
        row["video_id"]: DEFAULT_WEIGHT
        / (
            DEFAULT_WEIGHT
            + float(row["views"])
            + float(row["seconds"]) / SECONDS_PER_MINUTE / WATCHED_MINUTES_DIVISOR
        )
        for row in rows
    }


def weighted_sample_without_replacement(
    videos: list[VideoOut], weights: dict[str, float]
) -> list[VideoOut]:
    """Weighted shuffle without replacement in O(n log n) via exponential race.

    Each video draws a key ~ Exp(weight) and keys sort ascending
    (Efraimidis-Spirakis): higher-weight (less-watched) videos tend to come
    first while equal weights mix uniformly. Zero/negative weights never win
    a draw, so they trail in shuffled order.
    """
    keyed: list[tuple[float, VideoOut]] = []
    tail: list[VideoOut] = []
    for video in videos:
        weight = weights.get(video.id, DEFAULT_WEIGHT)
        if weight > 0:
            keyed.append((random.expovariate(weight), video))
        else:
            tail.append(video)
    keyed.sort(key=lambda item: item[0])
    if tail:
        random.shuffle(tail)
    return [video for _, video in keyed] + tail
