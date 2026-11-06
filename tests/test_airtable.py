from datetime import date

import pytest

from execution import airtable_leads as at
from tests.fakes import FakeAirtable


@pytest.mark.parametrize('raw', [
    'https://www.linkedin.com/in/avery-example-1a2b',
    'https://www.linkedin.com/in/avery-example-1a2b/',
    'http://linkedin.com/in/Avery-Example-1a2b',
    'linkedin.com/in/avery-example-1a2b?trk=public_profile',
    'https://uk.linkedin.com/in/avery-example-1a2b#about',
    '  www.linkedin.com/in/AVERY-EXAMPLE-1A2B/  ',
])
def test_profile_urls_normalise_to_one_form(raw):
    assert at.normalise_linkedin_url(raw) == 'https://www.linkedin.com/in/avery-example-1a2b'


@pytest.mark.parametrize('raw', [
    '', None, '   ', 'not a url',
    'https://www.linkedin.com/company/contoso',
    'https://www.linkedin.com/in/',
    'https://www.linkedin.com/posts/avery-example_activity-123',
    'https://example.com/in/avery-example',
    'https://linkedin.com.evil.example/in/avery-example',
])
def test_non_profile_urls_are_rejected(raw):
    assert at.normalise_linkedin_url(raw) == ''


def test_name_and_company_key_ignores_case_punctuation_and_suffixes():
    a = at.prospect_keys('Blake Sample', 'Contoso Ltd')
    b = at.prospect_keys('  blake  SAMPLE ', 'CONTOSO, Limited')
    assert a == b == {'nc:blake sample|contoso'}


def test_keys_include_every_identity_available():
    keys = at.prospect_keys('Avery Example', 'Northwind', 'linkedin.com/in/avery-example-1a2b', 'Avery@Example.org')
    assert keys == {'li:avery-example-1a2b', 'em:avery@example.org', 'nc:avery example|northwind'}


def test_existing_keys_follow_pagination(fake_airtable):
    for i in range(250):
        fake_airtable._create({at.F_NAME: f'Person {i}', at.F_COMPANY: 'Fabrikam'})
    keys = at.existing_prospect_keys()
    assert len(keys) == 250
    assert len([c for c in fake_airtable.calls if c[0] == 'get']) == 3


def test_add_lead_rejects_unknown_status_without_calling_airtable(fake_airtable):
    assert at.add_lead('Avery Example', '', 'Hi', status='Engaged') is None
    assert fake_airtable.calls == []


def test_add_lead_drops_a_non_profile_url(fake_airtable):
    at.add_lead('Avery Example', 'https://www.linkedin.com/company/contoso', 'Hi')
    assert at.F_URL not in fake_airtable.records[0]['fields']


def test_add_lead_returns_none_when_airtable_rejects_the_write(fake_airtable):
    fake_airtable.fail_create_for = {'Avery Example'}
    assert at.add_lead('Avery Example', '', 'Hi') is None


def test_contacted_status_stamps_last_contacted(fake_airtable):
    fake_airtable._create({at.F_NAME: 'Avery Example', at.F_STATUS: 'Not Contacted'})
    assert at.set_status('avery', 'contacted') is True
    fields = fake_airtable.records[0]['fields']
    assert fields[at.F_STATUS] == 'Contacted'
    assert fields[at.F_LAST_CONTACTED] == date.today().isoformat()


def test_engaged_alias_sets_reply_status(fake_airtable):
    fake_airtable._create({at.F_NAME: 'Avery Example', at.F_REPLY: 'No Reply'})
    assert at.set_status('Avery Example', 'Engaged') is True
    assert fake_airtable.records[0]['fields'][at.F_REPLY] == 'Replied'


def test_unknown_status_is_refused_before_any_write(fake_airtable):
    fake_airtable._create({at.F_NAME: 'Avery Example'})
    assert at.set_status('Avery Example', 'warm-ish') is False
    assert fake_airtable.writes() == []


def test_names_with_quotes_dont_break_the_search_formula(fake_airtable):
    fake_airtable._create({at.F_NAME: 'Dana O"Neill'})
    assert at.find_record('O"Neill')['fields'][at.F_NAME] == 'Dana O"Neill'


def test_missing_config_fails_clearly(monkeypatch):
    monkeypatch.delenv('AIRTABLE_BASE_ID')
    with pytest.raises(at.AirtableConfigError):
        at.list_all_records()


def test_outage_surfaces_as_airtable_error(fake_airtable):
    fake_airtable.network_down = True
    with pytest.raises(at.AirtableError):
        at.list_all_records()
