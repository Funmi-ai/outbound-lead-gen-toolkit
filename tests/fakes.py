"""Test doubles. All data here is synthetic."""

import json as _json
import re

import requests

from execution.airtable_leads import F_NAME, F_REPLY, F_STATUS, LEAD_STATUSES, REPLY_STATUSES

# Single-select options as configured in the Airtable base (Airtable rejects anything else).
SELECT_OPTIONS = {
    F_STATUS: set(LEAD_STATUSES.values()),
    F_REPLY: set(REPLY_STATUSES.values()),
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = _json.dumps(payload)

    def json(self):
        return self._payload


class FakeAirtable:
    """In-memory stand-in for the Airtable REST API.

    Emulates 100-record pagination with offsets, the two filterByFormula shapes the
    toolkit uses, single-select validation, and injectable outages and write failures.
    """

    def __init__(self, records=None):
        self.records = []
        self.calls = []
        self.network_down = False
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

    @staticmethod
    def _invalid_option(fields):
        for field, allowed in SELECT_OPTIONS.items():
            if field in fields and fields[field] not in allowed:
                return FakeResponse(422, {'error': {
                    'type': 'INVALID_MULTIPLE_CHOICE_OPTIONS',
                    'message': f'Insufficient permissions to create new select option "{fields[field]}"'}})
        return None

    @staticmethod
    def _matches(record, formula):
        find = re.fullmatch(r'FIND\(LOWER\("(.*)"\), LOWER\(\{Name\}\)\)', formula)
        if find:
            needle = find.group(1).replace('\\"', '"').replace('\\\\', '\\').lower()
            return needle in record['fields'].get(F_NAME, '').lower()
        equals = re.fullmatch(r'\{(.+?)\} = "(.*)"', formula)
        if equals:
            return record['fields'].get(equals.group(1)) == equals.group(2)
        raise AssertionError(f'FakeAirtable does not understand formula: {formula}')

    def get(self, url, headers=None, params=None, timeout=None):
        self._check_network()
        self.calls.append(('get', url, dict(params or {})))
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
            invalid = self._invalid_option(fields)
            if invalid:
                return invalid
            if fields.get(F_NAME) in self.fail_create_for:
                return FakeResponse(503, {'error': {'type': 'SERVICE_UNAVAILABLE'}})
            created.append(self._create(fields))
        return FakeResponse(200, {'records': created})

    def patch(self, url, headers=None, json=None, timeout=None):
        self._check_network()
        self.calls.append(('patch', url, json))
        record_id = url.rstrip('/').rsplit('/', 1)[1]
        record = next((r for r in self.records if r['id'] == record_id), None)
        if record is None:
            return FakeResponse(404, {'error': 'NOT_FOUND'})
        invalid = self._invalid_option(json['fields'])
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
        if lead['name'] in self.empty_for:
            text = ''
        else:
            text = f"Hi {lead['name'].split()[0]}"
        return {
            'connection_request': {'message': text},
            'value_follow_up': {'message': text and text + ' (touch 2)'},
            'soft_cta': {'message': text and text + ' (touch 3)'},
        }
