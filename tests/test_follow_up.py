import pytest

from execution import airtable_leads as at
from execution import follow_up_tracker as fu
from tests.fakes import LIVE_SCHEMA


def rec(status, days=None, reply='No Reply', **extra):
    fields = {at.F_NAME: 'Avery Example', at.F_STATUS: status, at.F_REPLY: reply, **extra}
    if days is not None:
        fields[at.F_DAYS_SINCE_PROGRESS] = days
    return fields


@pytest.mark.parametrize('fields, expected', [
    (rec('Contacted', 1), None),                      # too early
    (rec('Contacted', 3), None),
    (rec('Contacted', 4), 'touch_2'),
    (rec('Contacted', 12), 'touch_2'),
    (rec('Followed Up', 9), None),
    (rec('Followed Up', 10), 'touch_3'),
    (rec('Contacted', 20, reply='Replied'), None),    # any reply stops the sequence
    (rec('Contacted', 20, reply='Interested'), None),
    (rec('Contacted', 20, reply='Not Interested'), None),
    (rec('Contacted', 20, **{at.F_IGNORE: True}), None),
    (rec('Contacted', 20, **{at.F_CALL_BOOKED: True}), None),
    (rec('Not Contacted', 40), None),
    (rec('Closed', 40), None),
    (rec('Contacted'), 'needs_date'),                  # blank day count: flagged, never assumed due
    (rec('Contacted', ''), 'needs_date'),
    (rec('Contacted', 6.0), 'touch_2'),                # formula values can arrive as floats
])
def test_follow_ups_are_due_by_days_not_status_alone(fields, expected):
    action, _ = fu.classify_follow_up(fields)
    assert action == expected


def test_a_missing_reply_status_counts_as_no_reply():
    fields = rec('Contacted', 5)
    del fields[at.F_REPLY]
    assert fu.classify_follow_up(fields)[0] == 'touch_2'


def test_only_statuses_the_live_table_accepts_drive_follow_ups():
    assert set(fu.FOLLOW_UP_RULES) <= set(LIVE_SCHEMA['Lead Gen Progress'][1])


def test_follow_ups_read_every_page_of_the_table(live_airtable):
    for i in range(130):
        live_airtable._create({at.F_NAME: f'Lead {i}', at.F_STATUS: 'Contacted',
                               at.F_REPLY: 'No Reply', at.F_DAYS_SINCE_PROGRESS: 5})
    due = fu.get_follow_ups(at.list_all_records())
    assert len(due['touch_2']) == 130


def test_report_lists_leads_that_cannot_be_scheduled():
    due = fu.get_follow_ups([{'id': 'rec1', 'fields': rec('Contacted')}])
    report = fu.format_followup_report(due)
    assert "no day count" in report
    assert 'Avery Example' in report
