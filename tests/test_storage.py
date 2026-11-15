from storage import UpdateStore


def test_update_store_deduplicates(tmp_path):
    store = UpdateStore(str(tmp_path / "bot.sqlite3"))
    store.initialize()

    assert store.has_processed(123) is False
    store.mark_processed(123)
    assert store.has_processed(123) is True

    # Marking the same update twice is safe.
    store.mark_processed(123)
    assert store.has_processed(123) is True
