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
    assert a == b == {'nc:blake sample|contoso', 'nn:blake sample'}


def test_keys_include_every_identity_available():
    keys = at.prospect_keys('Avery Example', 'Northwind', 'linkedin.com/in/avery-example-1a2b', 'Avery@Example.org')
    assert keys == {'li:avery-example-1a2b', 'em:avery@example.org',
                    'nc:avery example|northwind', 'nn:avery example'}


def test_stored_records_with_a_company_dont_match_on_name_alone(fake_airtable):
    fake_airtable._create({at.F_NAME: 'Sam Lee', at.F_COMPANY: 'Contoso'})
    fake_airtable._create({at.F_NAME: 'Jo Park'})
    keys = at.existing_prospect_keys()
    assert 'nn:sam lee' not in keys
    assert 'nn:jo park' in keys


def test_canonical_statuses_match_the_live_table():
    from tests.fakes import LIVE_SCHEMA
    assert at.STATUS_ORDER == LIVE_SCHEMA['Lead Gen Progress'][1]
    assert list(at.REPLY_STATUSES.values()) == LIVE_SCHEMA['Reply Status'][1]


def test_live_table_rejects_a_company_field(live_airtable):
    # Why the original pipeline's Airtable writes would fail: it always sent Company.
    response = live_airtable.post('url', json={'records': [{'fields': {at.F_NAME: 'X', at.F_COMPANY: 'Y'}}]})
    assert response.status_code == 422


def test_add_lead_only_writes_fields_the_table_has(live_airtable):
    assert at.add_lead('Avery Example', '', 'Hi', role='CMO', company='Northwind') is not None
    fields = live_airtable.records[0]['fields']
    assert at.F_COMPANY not in fields
    assert fields[at.F_ROLE] == 'CMO'


def test_company_is_written_when_the_table_has_it(fake_airtable):
    at.add_lead('Avery Example', '', 'Hi', company='Northwind')
    assert fake_airtable.records[0]['fields'][at.F_COMPANY] == 'Northwind'


def test_without_metadata_access_a_missing_field_fails_loudly(live_airtable):
    live_airtable.metadata_forbidden = True
    assert at.add_lead('Avery Example', '', 'Hi', company='Northwind') is None
    assert live_airtable.records == []


def test_missing_required_field_refuses_the_write(monkeypatch):
    from tests.fakes import FakeAirtable, LIVE_SCHEMA
    schema = {k: v for k, v in LIVE_SCHEMA.items() if k != at.F_STATUS}
    fake = FakeAirtable(schema=schema)
    monkeypatch.setattr(at, '_session', fake)
    assert at.add_lead('Avery Example', '', 'Hi') is None
    assert fake.writes() == []


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


def test_contacted_status_writes_only_the_status(live_airtable):
    # The day count comes from the table's formula, so nothing else needs writing.
    live_airtable._create({at.F_NAME: 'Avery Example', at.F_STATUS: 'Not Contacted'})
    assert at.set_status('avery', 'contacted') is True
    assert live_airtable.writes()[-1][2] == {'fields': {at.F_STATUS: 'Contacted'}}


def test_engaged_alias_sets_reply_status(live_airtable):
    live_airtable._create({at.F_NAME: 'Avery Example', at.F_REPLY: 'No Reply'})
    assert at.set_status('Avery Example', 'Engaged') is True
    assert live_airtable.records[0]['fields'][at.F_REPLY] == 'Replied'


def test_interested_is_a_valid_reply_status(live_airtable):
    live_airtable._create({at.F_NAME: 'Avery Example', at.F_REPLY: 'No Reply'})
    assert at.set_status('Avery Example', 'interested') is True
    assert live_airtable.records[0]['fields'][at.F_REPLY] == 'Interested'


@pytest.mark.parametrize('status', ['warm-ish', 'nurture'])
def test_unknown_status_is_refused_before_any_write(live_airtable, status):
    live_airtable._create({at.F_NAME: 'Avery Example'})
    assert at.set_status('Avery Example', status) is False
    assert live_airtable.writes() == []


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
