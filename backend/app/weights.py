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
    pool = list(videos)
    remaining_weights = [weights.get(video.id, DEFAULT_WEIGHT) for video in pool]
    picked: list[VideoOut] = []
    while pool:
        total_weight = sum(remaining_weights)
        if total_weight <= 0:
            random.shuffle(pool)
            picked.extend(pool)
            break
        threshold = random.uniform(0, total_weight)
        cumulative_weight = 0.0
        selected_index = 0
        for index, weight in enumerate(remaining_weights):
            cumulative_weight += weight
            if threshold <= cumulative_weight:
                selected_index = index
                break
        else:
            selected_index = len(pool) - 1
        picked.append(pool.pop(selected_index))
        remaining_weights.pop(selected_index)
    return picked
