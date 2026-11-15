from emoji_pool import EMOJI_POOL, SAFE_FALLBACK_EMOJIS, build_emoji_pool


def test_pool_contains_at_least_500_unique_candidates():
    pool = build_emoji_pool()
    assert len(pool) >= 500
    assert len(pool) == len(set(pool))


def test_pool_includes_common_reaction_fallbacks():
    assert set(SAFE_FALLBACK_EMOJIS).issubset(set(EMOJI_POOL))


def test_pool_is_not_empty():
    assert len(EMOJI_POOL) >= 500
