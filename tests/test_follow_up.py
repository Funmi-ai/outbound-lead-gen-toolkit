from datetime import date, timedelta

import pytest

from execution import airtable_leads as at
from execution import follow_up_tracker as fu

TODAY = date(2026, 11, 20)


def rec(status, days_ago=None, reply='No Reply', raw_date=None):
    fields = {at.F_NAME: 'Avery Example', at.F_STATUS: status, at.F_REPLY: reply}
    if raw_date is not None:
        fields[at.F_LAST_CONTACTED] = raw_date
    elif days_ago is not None:
        fields[at.F_LAST_CONTACTED] = (TODAY - timedelta(days=days_ago)).isoformat()
    return fields


@pytest.mark.parametrize('fields, expected', [
    (rec('Contacted', 1), None),               # too early
    (rec('Contacted', 3), None),
    (rec('Contacted', 4), 'touch_2'),
    (rec('Contacted', 12), 'touch_2'),
    (rec('Followed Up', 9), None),
    (rec('Followed Up', 10), 'touch_3'),
    (rec('Nurture', 29), None),
    (rec('Nurture', 30), 're_engage'),
    (rec('Contacted', 20, reply='Replied'), None),   # a reply always stops the sequence
    (rec('Not Contacted', 40), None),
    (rec('Closed', 40), None),
    (rec('Contacted'), 'needs_date'),                 # no date: flagged, never assumed due
    (rec('Contacted', raw_date='last Tuesday'), 'needs_date'),
    (rec('Followed Up', raw_date='2026-11-15T09:30:00.000Z'), None),  # Airtable datetime format
])
def test_follow_ups_are_due_by_date_not_status_alone(fields, expected):
    action, _ = fu.classify_follow_up(fields, TODAY)
    assert action == expected


def test_only_canonical_statuses_drive_follow_ups():
    assert set(fu.FOLLOW_UP_RULES) <= set(at.LEAD_STATUSES.values())


def test_follow_ups_read_every_page_of_the_base(fake_airtable):
    stale = (date.today() - timedelta(days=5)).isoformat()
    for i in range(130):
        fake_airtable._create({at.F_NAME: f'Lead {i}', at.F_STATUS: 'Contacted',
                               at.F_REPLY: 'No Reply', at.F_LAST_CONTACTED: stale})
    due = fu.get_follow_ups(at.list_all_records())
    assert len(due['touch_2']) == 130


def test_report_lists_leads_that_cannot_be_scheduled():
    due = fu.get_follow_ups([{'id': 'rec1', 'fields': rec('Contacted')}], TODAY)
    report = fu.format_followup_report(due)
    assert "no Last Contacted date" in report
    assert 'Avery Example' in report
