#!/usr/bin/env python3
"""
Airtable Leads — the shared CRM store for the outbound toolkit.

USAGE:
  python3 -m execution.airtable_leads add "Name" "LinkedIn URL" "Message" [status]
  python3 -m execution.airtable_leads update "Name" status=Contacted reply=Replied
  python3 -m execution.airtable_leads status "Name" contacted
  python3 -m execution.airtable_leads list [limit] [status]
  python3 -m execution.airtable_leads pipeline

Config (.env): AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE (default "Leads").

Required table fields: Name, LinkedIn URL, Company, Role, Personalised Message,
Lead Gen Progress (single select, options = LEAD_STATUSES), Reply Status (single
select, options = REPLY_STATUSES), Last Contacted (date).
"""

import os
import re
import sys
import unicodedata
from datetime import date
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

# HTTP layer; tests swap this for an in-memory fake.
_session = requests

# Canonical status vocabulary. Every module imports these, and the Airtable
# single-select options must match them exactly.
LEAD_STATUSES = {
    'not_contacted': 'Not Contacted',
    'contacted': 'Contacted',        # Touch 1 sent
    'followed_up': 'Followed Up',    # Touch 2 sent
    'nurture': 'Nurture',            # No reply after the sequence
    'closed': 'Closed',
}
REPLY_STATUSES = {
    'no_reply': 'No Reply',
    'replied': 'Replied',
}
# Older notes used "Engaged" for a lead that replied.
STATUS_ALIASES = {'engaged': 'replied'}
STATUS_ORDER = list(LEAD_STATUSES.values())
# Moving a lead into one of these records an outbound touch, so it stamps Last Contacted.
TOUCH_STATUSES = {LEAD_STATUSES['contacted'], LEAD_STATUSES['followed_up']}

F_NAME = 'Name'
F_URL = 'LinkedIn URL'
F_COMPANY = 'Company'
F_ROLE = 'Role'
F_MESSAGE = 'Personalised Message'
F_STATUS = 'Lead Gen Progress'
F_REPLY = 'Reply Status'
F_LAST_CONTACTED = 'Last Contacted'

FIELD_ALIASES = {
    'status': F_STATUS, 'reply': F_REPLY, 'dm': F_MESSAGE, 'role': F_ROLE,
    'name': F_NAME, 'url': F_URL, 'company': F_COMPANY, 'last_contacted': F_LAST_CONTACTED,
}


class AirtableConfigError(RuntimeError):
    pass


class AirtableError(RuntimeError):
    pass


def _config():
    api_key = os.getenv('AIRTABLE_API_KEY')
    base_id = os.getenv('AIRTABLE_BASE_ID')
    table = os.getenv('AIRTABLE_TABLE', 'Leads')
    if not api_key or not base_id:
        raise AirtableConfigError('Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID in .env')
    url = f'https://api.airtable.com/v0/{base_id}/{table}'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    return url, headers


# ---------------------------------------------------------------------------
# Prospect identity
# ---------------------------------------------------------------------------
_PROFILE_PATH = re.compile(r'^/in/([A-Za-z0-9\-_%]+)/?$')
_COMPANY_SUFFIXES = re.compile(r'\b(ltd|limited|inc|incorporated|llc|plc|gmbh|corp|corporation|co)\b')


def normalise_linkedin_url(url: Optional[str]) -> str:
    """Canonical LinkedIn profile URL, or '' if this isn't a /in/ profile URL.

    This checks the format only. It can't confirm the profile belongs to the right person.
    """
    if not url or not url.strip():
        return ''
    url = url.strip()
    if not re.match(r'^https?://', url, re.I):
        url = 'https://' + url
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host != 'linkedin.com' and not host.endswith('.linkedin.com'):
        return ''
    match = _PROFILE_PATH.match(parsed.path)
    if not match:
        return ''
    return f'https://www.linkedin.com/in/{match.group(1).lower()}'


def _norm_text(text: Optional[str]) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    text = re.sub(r'[^a-z0-9 ]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def _norm_company(company: Optional[str]) -> str:
    return re.sub(r'\s+', ' ', _COMPANY_SUFFIXES.sub(' ', _norm_text(company))).strip()


def prospect_keys(name: str, company: str = '', linkedin_url: str = '', email: str = '') -> Set[str]:
    """Every stable identity we can derive for a prospect.

    Two records are the same prospect if any key matches: the LinkedIn profile slug,
    the email address, or normalised name + company (so a record saved without a URL
    still matches the same person later supplied with one).
    """
    keys = set()
    url = normalise_linkedin_url(linkedin_url)
    if url:
        keys.add('li:' + url.rsplit('/in/', 1)[1])
    if email and '@' in email:
        keys.add('em:' + email.strip().lower())
    norm_name = _norm_text(name)
    if norm_name:
        keys.add(f'nc:{norm_name}|{_norm_company(company)}')
    return keys


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request(method: str, url: str, headers: Dict, **kwargs) -> Dict:
    try:
        resp = getattr(_session, method)(url, headers=headers, timeout=30, **kwargs)
    except requests.RequestException as e:
        raise AirtableError(f'Airtable unreachable: {e}') from e
    if resp.status_code != 200:
        raise AirtableError(f'Airtable {method.upper()} failed ({resp.status_code}): {resp.text[:300]}')
    return resp.json()


def _quote(value: str) -> str:
    """Escape a value for use inside an Airtable formula string literal."""
    return value.replace('\\', '\\\\').replace('"', '\\"')


def list_all_records(filter_formula: Optional[str] = None) -> List[Dict]:
    """Every record in the table (following Airtable's 100-per-page offsets)."""
    url, headers = _config()
    records, offset = [], None
    while True:
        params = {'pageSize': 100}
        if offset:
            params['offset'] = offset
        if filter_formula:
            params['filterByFormula'] = filter_formula
        data = _request('get', url, headers, params=params)
        records.extend(data.get('records', []))
        offset = data.get('offset')
        if not offset:
            return records


def existing_prospect_keys() -> Set[str]:
    """Identity keys for every lead already in Airtable."""
    keys = set()
    for record in list_all_records():
        fields = record.get('fields', {})
        keys |= prospect_keys(fields.get(F_NAME, ''), fields.get(F_COMPANY, ''), fields.get(F_URL, ''))
    return keys


def find_record(name_search: str) -> Optional[Dict]:
    """First record whose name contains the search text (case-insensitive)."""
    formula = f'FIND(LOWER("{_quote(name_search)}"), LOWER({{{F_NAME}}}))'
    records = list_all_records(formula)
    return records[0] if records else None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def add_lead(name: str, linkedin_url: str, dm_message: str, status: str = 'Not Contacted',
             role: str = None, company: str = None) -> Optional[str]:
    """Create a lead. Returns the Airtable record ID, or None if it wasn't created.

    A LinkedIn URL is stored only if it's a well-formed profile URL; anything else is
    left blank rather than saved as if it were real.
    """
    if status not in STATUS_ORDER:
        print(f'x Unknown status "{status}". Use one of: {", ".join(STATUS_ORDER)}')
        return None
    url, headers = _config()
    fields = {
        F_NAME: name,
        F_MESSAGE: dm_message,
        F_STATUS: status,
        F_REPLY: REPLY_STATUSES['no_reply'],
    }
    clean_url = normalise_linkedin_url(linkedin_url)
    if clean_url:
        fields[F_URL] = clean_url
    if role:
        fields[F_ROLE] = role
    if company:
        fields[F_COMPANY] = company
    if status in TOUCH_STATUSES:
        fields[F_LAST_CONTACTED] = date.today().isoformat()

    try:
        data = _request('post', url, headers, json={'records': [{'fields': fields}]})
    except AirtableError as e:
        print(f'x Could not add {name}: {e}')
        return None
    rec_id = data['records'][0]['id']
    print(f'+ Added {name} ({rec_id})')
    return rec_id


def update_lead(name_search: str, **fields) -> bool:
    """Update the first lead matching a name. Field names can be aliases (status, reply, url…)."""
    url, headers = _config()
    mapped = {FIELD_ALIASES.get(k.lower(), k): v for k, v in fields.items()}

    if F_STATUS in mapped and mapped[F_STATUS] not in STATUS_ORDER:
        print(f'x Unknown status "{mapped[F_STATUS]}". Use one of: {", ".join(STATUS_ORDER)}')
        return False
    if F_REPLY in mapped and mapped[F_REPLY] not in REPLY_STATUSES.values():
        print(f'x Unknown reply status "{mapped[F_REPLY]}". Use one of: {", ".join(REPLY_STATUSES.values())}')
        return False
    if F_URL in mapped:
        clean = normalise_linkedin_url(mapped[F_URL])
        if not clean:
            print(f'x "{mapped[F_URL]}" is not a LinkedIn profile URL')
            return False
        mapped[F_URL] = clean
    if mapped.get(F_STATUS) in TOUCH_STATUSES and F_LAST_CONTACTED not in mapped:
        mapped[F_LAST_CONTACTED] = date.today().isoformat()

    try:
        record = find_record(name_search)
        if not record:
            print(f'x No record found for "{name_search}"')
            return False
        _request('patch', f"{url}/{record['id']}", headers, json={'fields': mapped})
    except AirtableError as e:
        print(f'x {e}')
        return False
    print(f"+ Updated {record['fields'].get(F_NAME, name_search)}: {list(mapped.keys())}")
    return True


def set_status(name_search: str, status: str) -> bool:
    """Set a lead's progress (contacted, followed_up, nurture, closed…) or reply status (replied)."""
    key = status.strip().lower().replace(' ', '_').replace('-', '_')
    key = STATUS_ALIASES.get(key, key)
    if key in LEAD_STATUSES:
        return update_lead(name_search, status=LEAD_STATUSES[key])
    if key in REPLY_STATUSES:
        return update_lead(name_search, reply=REPLY_STATUSES[key])
    print(f'x Unknown status "{status}". Progress: {", ".join(STATUS_ORDER)}. '
          f'Reply: {", ".join(REPLY_STATUSES.values())}.')
    return False


# ---------------------------------------------------------------------------
# Reads for the CLI
# ---------------------------------------------------------------------------
def list_leads(limit: int = 10, status_filter: str = None) -> List[Dict]:
    formula = None
    if status_filter:
        key = status_filter.strip().lower().replace(' ', '_')
        formula = f'{{{F_STATUS}}} = "{_quote(LEAD_STATUSES.get(key, status_filter))}"'
    records = sorted(list_all_records(formula), key=lambda r: r['fields'].get(F_NAME, ''))[:limit]

    print(f'\n{"Name":<25} {"Role":<20} {"Status":<15} {"Reply":<10}')
    print('-' * 75)
    for r in records:
        f = r['fields']
        print(f"{f.get(F_NAME, 'Unknown')[:24]:<25} {f.get(F_ROLE, '-')[:19]:<20} "
              f"{f.get(F_STATUS, '-')[:14]:<15} {f.get(F_REPLY, '-')[:9]:<10}")
    print()
    return records


def pipeline_overview() -> Dict:
    records = list_all_records()
    counts = {}
    for r in records:
        status = r['fields'].get(F_STATUS, 'Unknown')
        counts[status] = counts.get(status, 0) + 1

    print('\n' + '=' * 50 + '\nPIPELINE OVERVIEW\n' + '=' * 50)
    for status in STATUS_ORDER + [s for s in counts if s not in STATUS_ORDER]:
        if counts.get(status):
            print(f'{status:<20} {counts[status]:>4}  {"#" * min(counts[status], 20)}')
    print('-' * 50 + f'\nTotal Leads: {len(records)}\n')
    return {'total': len(records), 'by_status': counts}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1].lower()
    try:
        if cmd == 'add' and len(sys.argv) >= 5:
            status = sys.argv[5] if len(sys.argv) > 5 else 'Not Contacted'
            return 0 if add_lead(sys.argv[2], sys.argv[3], sys.argv[4], status) else 1
        if cmd == 'update' and len(sys.argv) >= 4:
            fields = dict(arg.split('=', 1) for arg in sys.argv[3:] if '=' in arg)
            return 0 if update_lead(sys.argv[2], **fields) else 1
        if cmd == 'status' and len(sys.argv) >= 4:
            return 0 if set_status(sys.argv[2], sys.argv[3]) else 1
        if cmd == 'list':
            limit, status_filter = 10, None
            if len(sys.argv) > 2:
                if sys.argv[2].isdigit():
                    limit = int(sys.argv[2])
                    status_filter = sys.argv[3] if len(sys.argv) > 3 else None
                else:
                    status_filter = sys.argv[2]
            list_leads(limit, status_filter)
            return 0
        if cmd == 'pipeline':
            pipeline_overview()
            return 0
    except (AirtableConfigError, AirtableError) as e:
        print(f'x {e}')
        return 2
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
