#!/usr/bin/env python3
"""
Follow-Up Tracker — works out which leads are due their next touch, by date.

Timing comes from the table's "Days Since Last Progress Update" formula (days since
"Lead Gen Progress" last changed — i.e. since the last touch was logged):
  Contacted   + no reply, 4+ days   -> Touch 2 (value follow-up)
  Followed Up + no reply, 10+ days  -> Touch 3 (soft CTA)
A lead is never listed if it has any reply (Replied, Interested, Not Interested), is
ticked Ignore or Call Booked, or is Not Contacted or Closed. Leads whose day count is
blank are listed separately instead of being assumed due.

Nothing is sent. With --generate it drafts the follow-up messages for a person to send.

USAGE:
  python3 -m execution.follow_up_tracker
  python3 -m execution.follow_up_tracker --generate
  python3 -m execution.follow_up_tracker -o followups.md
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execution import airtable_leads  # noqa: E402
from execution.airtable_leads import (  # noqa: E402
    F_CALL_BOOKED, F_COMPANY, F_DAYS_SINCE_PROGRESS, F_IGNORE, F_NAME, F_REPLY, F_ROLE,
    F_STATUS, F_URL, LEAD_STATUSES, REPLY_STATUSES,
)

# Minimum days since the last progress update before each follow-up is due.
TOUCH_TIMING = {'touch_2': 4, 'touch_3': 10}

# Which lead status leads to which follow-up. Only canonical statuses appear here.
FOLLOW_UP_RULES = {
    LEAD_STATUSES['contacted']: 'touch_2',
    LEAD_STATUSES['followed_up']: 'touch_3',
}

SECTIONS = [
    ('touch_2', 'Due Touch 2 (value follow-up)'),
    ('touch_3', 'Due Touch 3 (soft CTA)'),
    ('needs_date', "Can't schedule: no day count in Airtable"),
]


def _days(value) -> Optional[int]:
    if isinstance(value, bool) or value in (None, ''):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def classify_follow_up(fields: Dict) -> Tuple[Optional[str], str]:
    """(action, reason) for one Airtable record. action is None when nothing is due."""
    reply = fields.get(F_REPLY) or REPLY_STATUSES['no_reply']
    if reply != REPLY_STATUSES['no_reply']:
        return None, f'reply: {reply}'
    if fields.get(F_IGNORE):
        return None, 'ignored'
    if fields.get(F_CALL_BOOKED):
        return None, 'call booked'
    status = fields.get(F_STATUS, '')
    action = FOLLOW_UP_RULES.get(status)
    if not action:
        return None, f'status is {status or "blank"}'
    days = _days(fields.get(F_DAYS_SINCE_PROGRESS))
    if days is None:
        return 'needs_date', 'no day count since the last progress update'
    wait = TOUCH_TIMING[action]
    if days >= wait:
        return action, f'{days} days since the last touch'
    return None, f'{days} of {wait} days'


def get_follow_ups(records: List[Dict]) -> Dict[str, List[Dict]]:
    due = {key: [] for key, _ in SECTIONS}
    for record in records:
        fields = record.get('fields', {})
        action, reason = classify_follow_up(fields)
        if action:
            due[action].append({
                'id': record.get('id'),
                'name': fields.get(F_NAME, 'Unknown'),
                'title': fields.get(F_ROLE, ''),
                'company': fields.get(F_COMPANY, ''),
                'linkedin_url': fields.get(F_URL, ''),
                'reason': reason,
            })
    return due


def generate_followup_dm(lead: Dict, dm_manager, touch_type) -> str:
    lead_dict = {
        'name': lead.get('name', ''),
        'first_name': lead.get('name', '').split()[0] if lead.get('name') else '',
        'title': lead.get('title', ''),
        'company': lead.get('company', ''),
        'headline': lead.get('title', ''),
        'ai_signals': [],
    }
    return dm_manager.generate_dm(lead_dict, touch_type)


def format_followup_report(due: Dict[str, List[Dict]], dms: Dict[str, str] = None) -> str:
    lines = ['# Follow-Up Tracker', f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", '',
             '| Category | Count |', '|---|---|']
    lines += [f'| {label} | {len(due[key])} |' for key, label in SECTIONS]
    lines.append('')
    for key, label in SECTIONS:
        if not due[key]:
            continue
        lines += [f'## {label}', '']
        if key == 'needs_date':
            lines += ['*Re-set "Lead Gen Progress" for these in Airtable so the day count starts, then re-run.*', '']
        for lead in due[key]:
            lines += [f"### {lead['name']}",
                      f"**Title:** {lead['title'] or '-'}  **Company:** {lead['company'] or '-'}",
                      f"**LinkedIn:** {lead['linkedin_url'] or 'missing'}",
                      f"**Why:** {lead['reason']}"]
            if dms and lead['id'] in dms:
                lines += ['', '```', dms[lead['id']], '```']
            lines.append('')
    if not any(due.values()):
        lines += ['## Nothing due today', '']
    return '\n'.join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='List leads due a follow-up touch')
    parser.add_argument('--generate', '-g', action='store_true', help='Draft the follow-up messages')
    parser.add_argument('--output', '-o', help='Save the report to a file')
    args = parser.parse_args(argv)

    try:
        records = airtable_leads.list_all_records()
    except (airtable_leads.AirtableError, airtable_leads.AirtableConfigError) as e:
        print(f'x {e}')
        return 2
    due = get_follow_ups(records)

    dms = {}
    if args.generate:
        from execution.dm_templates import DMSequenceManager, TouchType
        touch_types = {'touch_2': TouchType.VALUE_FOLLOW_UP, 'touch_3': TouchType.SOFT_CTA}
        manager = DMSequenceManager()
        for action, touch_type in touch_types.items():
            for lead in due[action]:
                dms[lead['id']] = generate_followup_dm(lead, manager, touch_type)

    report = format_followup_report(due, dms)
    print(report)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f'\nSaved to: {args.output}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
