import pytest
from app import store


@pytest.fixture(autouse=True)
def mainland_region(monkeypatch):
    # The pre-existing suites describe the mainland edition; region tests override this.
    monkeypatch.setenv('REGION', 'cn')


@pytest.fixture(autouse=True)
def empty_store():
    # The in-memory store caps temporary documents at 20; keep tests independent of each other.
    yield
    with store.lock, store.connection:
        for table in ('documents', 'versions', 'reports', 'tools'):
            store.connection.execute(f'DELETE FROM {table}')


@pytest.fixture(autouse=True)
def pseudonym_key_in_tmp(tmp_path, monkeypatch):
    # Never touch the user's data/pseudonym.key from tests.
    from app.profiles import hk
    monkeypatch.setenv('PSEUDONYM_KEY_FILE', str(tmp_path / 'pseudonym.key'))
    monkeypatch.setattr(hk, '_KEY', None)
