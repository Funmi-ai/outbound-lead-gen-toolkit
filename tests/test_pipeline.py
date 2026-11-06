import csv

import pytest

from execution import airtable_leads as at
from execution import lead_pipeline as lp
from tests.fakes import FakeDM

FIELDS = ('name', 'title', 'company', 'linkedin_url', 'location')

ROWS = [
    {'name': 'Avery Example', 'title': 'CMO', 'company': 'Northwind Traders Ltd',
     'linkedin_url': 'https://www.linkedin.com/in/avery-example-1a2b/', 'location': 'London, United Kingdom'},
    {'name': 'Blake Sample', 'title': 'Head of Growth', 'company': 'Contoso', 'location': 'Toronto, Canada'},
    {'name': 'Casey Placeholder', 'title': 'Marketing Manager', 'company': 'Fabrikam Inc'},
]


def write_csv(path, rows, fields=FIELDS):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in fields})
    return str(path)


def run(tmp_path, rows, sync, dm=None):
    leads, _ = lp.load_leads_csv(write_csv(tmp_path / 'leads.csv', rows))
    pipeline = lp.LeadPipeline(dm_manager=dm or FakeDM(), store=lp.AirtableStore() if sync else None,
                               sleep=lambda s: None)
    processed, summary = pipeline.process(leads, sync=sync)
    return {l.name: l for l in processed}, summary


# --- Defect 1: scores used to be thrown away (every lead showed 0/100) ---------------

def test_scores_are_carried_through(tmp_path):
    leads, _ = run(tmp_path, ROWS, sync=False)
    assert (leads['Avery Example'].warmth_score, leads['Avery Example'].qualification) == (30, 'cool')  # CMO + UK
    assert leads['Blake Sample'].warmth_score == 25                                                  # Head of + Canada
    assert leads['Casey Placeholder'].warmth_score == 0                                              # off-ICP title
    assert 'Growth Mindset' in leads['Blake Sample'].ai_signals


# --- Defect 2: LinkedIn URLs used to be guessed from names -------------------------------

def test_linkedin_urls_are_never_guessed(tmp_path):
    leads, summary = run(tmp_path, ROWS, sync=False)
    assert leads['Blake Sample'].linkedin_url == ''
    assert leads['Blake Sample'].linkedin_status == 'missing'
    assert leads['Avery Example'].linkedin_url == 'https://www.linkedin.com/in/avery-example-1a2b'
    assert summary.missing_linkedin == 2


def test_a_non_profile_url_is_dropped_not_stored(tmp_path, fake_airtable):
    rows = [dict(ROWS[1], linkedin_url='https://www.linkedin.com/company/contoso')]
    leads, summary = run(tmp_path, rows, sync=True)
    assert leads['Blake Sample'].linkedin_status == 'rejected'
    assert summary.rejected_linkedin == 1
    assert at.F_URL not in fake_airtable.records[0]['fields']


def test_report_says_missing_instead_of_inventing_a_url(tmp_path):
    leads, summary = run(tmp_path, ROWS, sync=False)
    report = lp.generate_outreach_report(list(leads.values()), summary)
    assert 'missing: find and confirm their profile' in report
    assert 'linkedin.com/in/blake' not in report


def test_new_leads_are_written_with_canonical_values(tmp_path, fake_airtable):
    run(tmp_path, ROWS, sync=True)
    assert len(fake_airtable.records) == 3
    for record in fake_airtable.records:
        assert record['fields'][at.F_STATUS] == 'Not Contacted'
        assert record['fields'][at.F_REPLY] == 'No Reply'


def test_pipeline_works_against_the_live_table_shape(tmp_path, live_airtable):
    # The live table has no Company field; the original pipeline always sent one.
    _, summary = run(tmp_path, ROWS, sync=True)
    assert (summary.added, summary.failed) == (3, 0)
    assert all(at.F_COMPANY not in r['fields'] for r in live_airtable.records)


def test_rerun_against_the_live_table_adds_nothing(tmp_path, live_airtable):
    # With no stored company, a re-run must still recognise the same people.
    run(tmp_path, ROWS, sync=True)
    _, summary = run(tmp_path, ROWS, sync=True)
    assert (summary.added, summary.duplicates) == (0, 3)
    assert len(live_airtable.records) == 3


def test_company_less_record_matches_a_new_lead_by_name(tmp_path, live_airtable):
    live_airtable._create({at.F_NAME: 'Blake Sample'})
    leads, _ = run(tmp_path, ROWS, sync=True)
    assert leads['Blake Sample'].outcome == 'duplicate'


def test_same_name_at_different_companies_in_one_file_are_both_kept(tmp_path, fake_airtable):
    rows = [{'name': 'Sam Lee', 'title': 'CMO', 'company': 'Contoso'},
            {'name': 'Sam Lee', 'title': 'VP Marketing', 'company': 'Fabrikam'}]
    _, summary = run(tmp_path, rows, sync=True)
    assert (summary.added, summary.duplicates) == (2, 0)


# --- Defect 5: dedupe used to be dead code ------------------------------------------------

def test_rerun_adds_nothing_and_spends_no_model_calls(tmp_path, fake_airtable):
    run(tmp_path, ROWS, sync=True)
    second_dm = FakeDM()
    _, summary = run(tmp_path, ROWS, sync=True, dm=second_dm)
    assert len(fake_airtable.records) == 3
    assert (summary.added, summary.duplicates) == (0, 3)
    assert second_dm.calls == []


def test_same_person_twice_in_one_file_is_added_once(tmp_path, fake_airtable):
    variant = dict(ROWS[0], linkedin_url='http://linkedin.com/in/Avery-Example-1a2b?trk=x')
    _, summary = run(tmp_path, [ROWS[0], variant], sync=True)
    assert len(fake_airtable.records) == 1
    assert summary.duplicates == 1


def test_existing_record_matches_on_name_and_company(tmp_path, fake_airtable):
    fake_airtable._create({at.F_NAME: 'Blake Sample', at.F_COMPANY: 'Contoso Ltd'})
    leads, _ = run(tmp_path, ROWS, sync=True)
    assert leads['Blake Sample'].outcome == 'duplicate'


def test_existing_record_matches_on_url_even_if_name_differs(tmp_path, fake_airtable):
    fake_airtable._create({at.F_NAME: 'A. Example', at.F_URL: 'https://linkedin.com/in/avery-example-1a2b'})
    leads, _ = run(tmp_path, ROWS, sync=True)
    assert leads['Avery Example'].outcome == 'duplicate'


# --- Failure cases ----------------------------------------------------------------------

def test_a_failed_write_is_reported_and_the_run_continues(tmp_path, fake_airtable):
    fake_airtable.fail_create_for = {'Blake Sample'}
    leads, summary = run(tmp_path, ROWS, sync=True)
    assert leads['Blake Sample'].outcome == 'failed'
    assert (summary.added, summary.failed) == (2, 1)


def test_a_failed_write_is_retried_on_the_next_run(tmp_path, fake_airtable):
    fake_airtable.fail_create_for = {'Blake Sample'}
    run(tmp_path, ROWS, sync=True)
    fake_airtable.fail_create_for = set()
    _, summary = run(tmp_path, ROWS, sync=True)
    assert (summary.added, summary.duplicates) == (1, 2)
    assert len(fake_airtable.records) == 3


def test_unreadable_airtable_stops_before_any_drafting_or_writing(tmp_path, fake_airtable):
    fake_airtable.network_down = True
    dm = FakeDM()
    with pytest.raises(lp.CRMUnavailable):
        run(tmp_path, ROWS, sync=True, dm=dm)
    assert dm.calls == []
    assert fake_airtable.records == []


def test_an_empty_draft_is_not_logged(tmp_path, fake_airtable):
    leads, summary = run(tmp_path, ROWS, sync=True, dm=FakeDM(empty_for={'Casey Placeholder'}))
    assert leads['Casey Placeholder'].outcome == 'failed'
    assert len(fake_airtable.records) == 2


def test_draft_only_mode_never_touches_airtable(tmp_path):
    # The autouse fixture makes any Airtable call fail the test.
    _, summary = run(tmp_path, ROWS, sync=False)
    assert summary.drafted_only == 3


# --- Defect 4: input path ---------------------------------------------------------------

def test_missing_csv_gives_a_clear_error_and_exit_code(tmp_path):
    missing = tmp_path / 'nope.csv'
    with pytest.raises(lp.LeadSourceError, match='not found'):
        lp.load_leads_csv(str(missing))
    assert lp.main(['--csv', str(missing)]) == 2


def test_csv_without_a_name_column_is_rejected(tmp_path):
    path = write_csv(tmp_path / 'bad.csv', [{'title': 'CMO'}], fields=('title', 'company'))
    with pytest.raises(lp.LeadSourceError, match='"name" column'):
        lp.load_leads_csv(path)


def test_rows_without_a_name_are_skipped_and_counted(tmp_path):
    path = write_csv(tmp_path / 'leads.csv', ROWS + [{'title': 'CMO', 'company': 'Nameless Co'}])
    leads, skipped = lp.load_leads_csv(path)
    assert (len(leads), skipped) == (3, 1)


def test_default_csv_path_points_at_the_data_folder():
    assert lp.DEFAULT_CSV.endswith('leads/data/conference_leads.csv')
