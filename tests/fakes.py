"""Test doubles. All data here is synthetic."""

import json as _json
import re

import requests

# Field name -> (type, single-select options or None).
# LIVE_SCHEMA mirrors the real Leads table's field names, types and options
# (read from the Airtable metadata API on 2026-11-06; no record data).
LIVE_SCHEMA = {
    'Name': ('singleLineText', None),
    'Role': ('singleLineText', None),
    'LinkedIn URL': ('singleLineText', None),
    'Personalised Message': ('multilineText', None),
    'Reply Status': ('singleSelect', ['No Reply', 'Replied', 'Interested', 'Not Interested']),
    'Ignore': ('checkbox', None),
    'Lead Gen Progress': ('singleSelect', ['Not Contacted', 'Contacted', 'Followed Up', 'Closed']),
    'Days Since Last Progress Update': ('formula', None),
    'Is Ignored or Closed': ('formula', None),
    'Reply Received Date': ('formula', None),
    'Reply Summary (AI)': ('aiText', None),
    'Lead Quality Assessment (AI)': ('aiText', None),
    'Call Booked': ('checkbox', None),
}
# A table that also has the optional Company field.
GENERIC_SCHEMA = dict(LIVE_SCHEMA, Company=('singleLineText', None))

COMPUTED_TYPES = {'formula', 'aiText'}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = _json.dumps(payload)

    def json(self):
        return self._payload


def _error(status, kind, message):
    return FakeResponse(status, {'error': {'type': kind, 'message': message}})


class FakeAirtable:
    """In-memory stand-in for the Airtable REST and metadata APIs.

    Emulates 100-record pagination, the two filterByFormula shapes the toolkit uses,
    the table schema (unknown fields, computed fields and invalid select options are
    rejected as the real API does), and injectable outages and write failures.
    """

    def __init__(self, schema=GENERIC_SCHEMA, records=None):
        self.schema = schema
        self.records = []
        self.calls = []
        self.network_down = False
        self.metadata_forbidden = False
        self.fail_create_for = set()
        self._next_id = 1
        for fields in records or []:
            self._create(fields)

    def _create(self, fields):
        record = {'id': f'rec{self._next_id:05d}', 'fields': dict(fields)}
        self._next_id += 1
        self.records.append(record)
        return record

    def _check_network(self):
        if self.network_down:
            raise requests.ConnectionError('simulated outage')

    def _validate_write(self, fields):
        for name, value in fields.items():
            if name not in self.schema:
                return _error(422, 'UNKNOWN_FIELD_NAME', f'Unknown field name: "{name}"')
            kind, options = self.schema[name]
            if kind in COMPUTED_TYPES:
                return _error(422, 'INVALID_VALUE_FOR_COLUMN', f'Field "{name}" cannot accept a value because the field is computed')
            if options is not None and value not in options:
                return _error(422, 'INVALID_MULTIPLE_CHOICE_OPTIONS',
                              f'Insufficient permissions to create new select option "{value}"')
        return None

    @staticmethod
    def _matches(record, formula):
        find = re.fullmatch(r'FIND\(LOWER\("(.*)"\), LOWER\(\{Name\}\)\)', formula)
        if find:
            needle = find.group(1).replace('\\"', '"').replace('\\\\', '\\').lower()
            return needle in record['fields'].get('Name', '').lower()
        equals = re.fullmatch(r'\{(.+?)\} = "(.*)"', formula)
        if equals:
            return record['fields'].get(equals.group(1)) == equals.group(2)
        raise AssertionError(f'FakeAirtable does not understand formula: {formula}')

    def _metadata(self):
        if self.metadata_forbidden:
            return _error(403, 'INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND', 'Token lacks schema.bases:read')
        fields = []
        for name, (kind, options) in self.schema.items():
            field = {'name': name, 'type': kind}
            if options is not None:
                field['options'] = {'choices': [{'name': o} for o in options]}
            fields.append(field)
        return FakeResponse(200, {'tables': [{'id': 'tblTEST', 'name': 'Leads', 'fields': fields}]})

    def get(self, url, headers=None, params=None, timeout=None):
        self._check_network()
        self.calls.append(('get', url, dict(params or {})))
        if '/meta/bases/' in url:
            return self._metadata()
        params = params or {}
        rows = self.records
        if params.get('filterByFormula'):
            rows = [r for r in rows if self._matches(r, params['filterByFormula'])]
        size = min(int(params.get('pageSize', 100)), 100)
        start = int(params.get('offset') or 0)
        payload = {'records': rows[start:start + size]}
        if start + size < len(rows):
            payload['offset'] = str(start + size)
        return FakeResponse(200, payload)

    def post(self, url, headers=None, json=None, timeout=None):
        self._check_network()
        self.calls.append(('post', url, json))
        created = []
        for item in json['records']:
            fields = item['fields']
            invalid = self._validate_write(fields)
            if invalid:
                return invalid
            if fields.get('Name') in self.fail_create_for:
                return _error(503, 'SERVICE_UNAVAILABLE', 'simulated failure')
            created.append(self._create(fields))
        return FakeResponse(200, {'records': created})

    def patch(self, url, headers=None, json=None, timeout=None):
        self._check_network()
        self.calls.append(('patch', url, json))
        record_id = url.rstrip('/').rsplit('/', 1)[1]
        record = next((r for r in self.records if r['id'] == record_id), None)
        if record is None:
            return _error(404, 'NOT_FOUND', 'record not found')
        invalid = self._validate_write(json['fields'])
        if invalid:
            return invalid
        record['fields'].update(json['fields'])
        return FakeResponse(200, record)

    def writes(self):
        return [c for c in self.calls if c[0] in ('post', 'patch')]


class FakeDM:
    """Stands in for DMSequenceManager so no model calls are made."""

    def __init__(self, empty_for=()):
        self.calls = []
        self.empty_for = set(empty_for)

    def generate_full_sequence(self, lead):
        self.calls.append(lead['name'])
        text = '' if lead['name'] in self.empty_for else f"Hi {lead['name'].split()[0]}"
        return {
            'connection_request': {'message': text},
            'value_follow_up': {'message': text and text + ' (touch 2)'},
            'soft_cta': {'message': text and text + ' (touch 3)'},
        }
