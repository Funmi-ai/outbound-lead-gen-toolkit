import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execution import airtable_leads  # noqa: E402
from tests.fakes import FakeAirtable  # noqa: E402


class _NoAirtable:
    def __getattr__(self, name):
        raise AssertionError('Test reached Airtable without the fake_airtable fixture')


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No test may touch the network, a real Airtable base or a paid API."""
    def blocked(*args, **kwargs):
        raise RuntimeError('Network access is blocked in tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    for key in ('ANTHROPIC_API_KEY', 'APOLLO_API_KEY', 'LINKEDIN_SESSION_COOKIE'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('AIRTABLE_API_KEY', 'test-key')
    monkeypatch.setenv('AIRTABLE_BASE_ID', 'appTEST00000000000')
    monkeypatch.setenv('AIRTABLE_TABLE', 'Leads')
    monkeypatch.setattr(airtable_leads, '_session', _NoAirtable())


@pytest.fixture
def fake_airtable(monkeypatch):
    fake = FakeAirtable()
    monkeypatch.setattr(airtable_leads, '_session', fake)
    return fake
