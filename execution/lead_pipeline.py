#!/usr/bin/env python3
"""
Lead Pipeline — turns a prospect list (CSV) into scored, deduplicated leads with
three-touch draft sequences, logged to Airtable.

Nothing is sent. Every message is a draft for a person to review and send.

Per lead:
  1. Load from CSV. Needs a "name" column; title, company, linkedin_url, email,
     location, headline, keywords, source and priority are optional.
  2. Check identity against Airtable and earlier rows in this run. Duplicates are
     skipped before any model calls are spent on them.
  3. Keep the LinkedIn URL only if the source supplied a well-formed profile URL;
     otherwise it stays explicitly missing. URLs are never guessed.
  4. Score with lead_scoring.py.
  5. Draft the three-touch sequence with dm_templates.py.
  6. Add to Airtable as "Not Contacted".
  7. Write a copy-paste outreach report with a run summary.

USAGE:
  python3 -m execution.lead_pipeline --csv path/to/leads.csv
  python3 -m execution.lead_pipeline --csv leads.csv --limit 10 -o outreach.md
  python3 -m execution.lead_pipeline --csv leads.csv --no-airtable    # drafts only, no CRM writes

Exit codes: 0 ok, 1 some leads failed, 2 bad input or config, 3 Airtable unreadable.
"""

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from execution import airtable_leads  # noqa: E402
from execution.lead_scoring import LeadScorer  # noqa: E402

DEFAULT_CSV = os.path.join(REPO_ROOT, 'leads', 'data', 'conference_leads.csv')


class LeadSourceError(RuntimeError):
    pass


class CRMUnavailable(RuntimeError):
    pass


@dataclass
class Lead:
    name: str
    title: str = ''
    company: str = ''
    source: str = 'csv'
    priority: str = 'medium'
    linkedin_url: str = ''
    linkedin_status: str = 'missing'   # provided | rejected | missing
    email: str = ''
    location: str = ''
    headline: str = ''
    keywords: str = ''
    warmth_score: int = 0
    qualification: str = ''
    ai_signals: List[str] = field(default_factory=list)
    dm_touch1: str = ''
    dm_touch2: str = ''
    dm_touch3: str = ''
    outcome: str = 'pending'           # added | drafted | duplicate | failed
    note: str = ''

    def scoring_input(self) -> Dict:
        return {
            'name': self.name,
            'title': self.title,
            'company': self.company,
            'location': self.location,
            'headline': self.headline or self.title,
            'keywords': self.keywords,
        }

    def identity_keys(self) -> Set[str]:
        return airtable_leads.prospect_keys(self.name, self.company, self.linkedin_url, self.email)


@dataclass
class RunSummary:
    loaded: int = 0
    skipped_no_name: int = 0
    added: int = 0
    drafted_only: int = 0
    duplicates: int = 0
    failed: int = 0
    missing_linkedin: int = 0
    rejected_linkedin: int = 0


def load_leads_csv(path: str) -> Tuple[List[Lead], int]:
    """Leads from a CSV, plus the count of rows skipped for having no name."""
    if not os.path.isfile(path):
        raise LeadSourceError(f'Lead file not found: {path}. Pass --csv with the path to your list.')
    leads, skipped = [], 0
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = [(h or '').strip().lower() for h in (reader.fieldnames or [])]
        if 'name' not in headers:
            raise LeadSourceError(f'{path} needs a "name" column (found: {", ".join(headers) or "none"})')
        for raw in reader:
            row = {(k or '').strip().lower(): (v.strip() if isinstance(v, str) else '')
                   for k, v in raw.items() if k}
            if not row.get('name'):
                skipped += 1
                continue
            supplied_url = row.get('linkedin_url', '')
            clean_url = airtable_leads.normalise_linkedin_url(supplied_url)
            leads.append(Lead(
                name=row['name'],
                title=row.get('title', ''),
                company=row.get('company', ''),
                source=row.get('source') or 'csv',
                priority=row.get('priority') or 'medium',
                linkedin_url=clean_url,
                linkedin_status='provided' if clean_url else ('rejected' if supplied_url else 'missing'),
                email=row.get('email', ''),
                location=row.get('location', ''),
                headline=row.get('headline', ''),
                keywords=row.get('keywords', ''),
            ))
    return leads, skipped


class AirtableStore:
    """Thin seam over airtable_leads, so the pipeline can be tested against a fake base."""

    def existing_keys(self) -> Set[str]:
        return airtable_leads.existing_prospect_keys()

    def add(self, lead: Lead) -> Optional[str]:
        return airtable_leads.add_lead(
            name=lead.name,
            linkedin_url=lead.linkedin_url,
            dm_message=lead.dm_touch1,
            status=airtable_leads.LEAD_STATUSES['not_contacted'],
            role=lead.title,
            company=lead.company,
        )


class LeadPipeline:
    def __init__(self, dm_manager=None, scorer: LeadScorer = None, store: AirtableStore = None,
                 sleep: Callable[[float], None] = time.sleep, pause_seconds: float = 0.5):
        self.dm_manager = dm_manager
        self.scorer = scorer or LeadScorer()
        self.store = store
        self.sleep = sleep
        self.pause_seconds = pause_seconds

    def _dm(self):
        if self.dm_manager is None:
            from execution.dm_templates import DMSequenceManager
            self.dm_manager = DMSequenceManager()
        return self.dm_manager

    def enrich(self, lead: Lead) -> Lead:
        data = lead.scoring_input()
        scored = self.scorer.score_lead(data)
        lead.warmth_score = scored['total_score']
        lead.qualification = scored['qualification']
        lead.ai_signals = self.scorer.detect_ai_signals(data)
        return lead

    def draft(self, lead: Lead) -> Lead:
        payload = lead.scoring_input()
        payload.update(warmth_score=lead.warmth_score, ai_signals=lead.ai_signals)
        sequence = self._dm().generate_full_sequence(payload)
        lead.dm_touch1 = sequence.get('connection_request', {}).get('message', '')
        lead.dm_touch2 = sequence.get('value_follow_up', {}).get('message', '')
        lead.dm_touch3 = sequence.get('soft_cta', {}).get('message', '')
        return lead

    def process(self, leads: List[Lead], sync: bool = True) -> Tuple[List[Lead], RunSummary]:
        summary = RunSummary(loaded=len(leads))
        seen: Set[str] = set()
        if sync:
            try:
                seen = set(self.store.existing_keys())
            except (airtable_leads.AirtableError, airtable_leads.AirtableConfigError) as e:
                raise CRMUnavailable(
                    "Couldn't read existing leads from Airtable, so duplicates can't be checked. "
                    f'Nothing was drafted or written. ({e})') from e

        processed = []
        for i, lead in enumerate(leads):
            keys = lead.identity_keys()
            if keys & seen:
                lead.outcome, lead.note = 'duplicate', 'Already in Airtable or earlier in this list'
                summary.duplicates += 1
                processed.append(lead)
                continue

            if lead.linkedin_status == 'missing':
                summary.missing_linkedin += 1
            elif lead.linkedin_status == 'rejected':
                summary.rejected_linkedin += 1

            self.enrich(lead)
            self.draft(lead)
            if not lead.dm_touch1:
                lead.outcome, lead.note = 'failed', 'Draft generation returned nothing, so it was not logged'
                summary.failed += 1
            elif sync:
                if self.store.add(lead):
                    lead.outcome = 'added'
                    summary.added += 1
                    seen |= keys
                else:
                    lead.outcome, lead.note = 'failed', 'Airtable write failed'
                    summary.failed += 1
            else:
                lead.outcome = 'drafted'
                summary.drafted_only += 1
                seen |= keys

            processed.append(lead)
            if self.pause_seconds and i < len(leads) - 1:
                self.sleep(self.pause_seconds)

        return processed, summary


def _linkedin_line(lead: Lead) -> str:
    if lead.linkedin_status == 'provided':
        return lead.linkedin_url + '  (from your list; check it is the right person)'
    if lead.linkedin_status == 'rejected':
        return 'missing: the URL in your list was not a LinkedIn profile, so it was dropped'
    return 'missing: find and confirm their profile before sending'


def generate_outreach_report(leads: List[Lead], summary: RunSummary) -> str:
    out = [
        '# Outreach drafts: review and send by hand',
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        '',
        '| Run summary | Count |',
        '|---|---|',
        f'| Rows loaded | {summary.loaded} |',
        f'| Rows skipped (no name) | {summary.skipped_no_name} |',
        f'| Added to Airtable | {summary.added} |',
        f'| Drafted only (no Airtable) | {summary.drafted_only} |',
        f'| Duplicates skipped | {summary.duplicates} |',
        f'| Failed | {summary.failed} |',
        f'| No LinkedIn URL | {summary.missing_linkedin + summary.rejected_linkedin} |',
        '',
    ]
    ready = sorted((l for l in leads if l.outcome in ('added', 'drafted')),
                   key=lambda l: l.warmth_score, reverse=True)
    for lead in ready:
        out += [
            '=' * 60,
            f'## {lead.name}',
            f'**Title:** {lead.title}',
            f'**Company:** {lead.company}',
            f'**LinkedIn:** {_linkedin_line(lead)}',
            f'**Warmth Score:** {lead.warmth_score}/100 ({lead.qualification})',
            f"**Signals:** {', '.join(lead.ai_signals) or 'none detected'}",
            f'**Source:** {lead.source}',
            '',
            '### Touch 1: Connection Request (Day 0)', '```', lead.dm_touch1, '```', '',
            '### Touch 2: Value Follow-Up (Day 4+)', '```', lead.dm_touch2, '```', '',
            '### Touch 3: Soft CTA (Day 10+ after Touch 2)', '```', lead.dm_touch3, '```', '',
        ]
    for label, outcome in (('Skipped as duplicates', 'duplicate'), ('Failed', 'failed')):
        rows = [l for l in leads if l.outcome == outcome]
        if rows:
            out += [f'## {label}', ''] + [f'- {l.name} ({l.company}): {l.note}' for l in rows] + ['']
    return '\n'.join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Score, deduplicate and draft outreach for a prospect list')
    parser.add_argument('--csv', default=DEFAULT_CSV, help=f'Prospect list (default: {DEFAULT_CSV})')
    parser.add_argument('--limit', type=int, default=0, help='Max leads to process (0 = all)')
    parser.add_argument('--output', '-o', help='Save the outreach report to a file')
    parser.add_argument('--no-airtable', action='store_true', help='Draft only; read and write nothing in Airtable')
    args = parser.parse_args(argv)

    try:
        leads, skipped = load_leads_csv(args.csv)
    except LeadSourceError as e:
        print(f'x {e}')
        return 2
    if args.limit:
        leads = leads[:args.limit]
    if not leads:
        print('x No leads with a name in that file.')
        return 2

    pipeline = LeadPipeline(store=None if args.no_airtable else AirtableStore())
    try:
        pipeline._dm()
    except ValueError as e:
        print(f'x {e}')
        return 2

    try:
        processed, summary = pipeline.process(leads, sync=not args.no_airtable)
    except CRMUnavailable as e:
        print(f'x {e}')
        return 3
    summary.skipped_no_name = skipped

    report = generate_outreach_report(processed, summary)
    print(report)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f'\nSaved to: {args.output}')
    return 1 if summary.failed else 0


if __name__ == '__main__':
    sys.exit(main())
