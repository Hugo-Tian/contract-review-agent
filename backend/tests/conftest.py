import pytest


@pytest.fixture(autouse=True)
def mainland_region(monkeypatch):
    # The pre-existing suites describe the mainland edition; region tests override this.
    monkeypatch.setenv('REGION', 'cn')
