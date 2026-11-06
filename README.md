# outbound-lead-gen-toolkit

A small toolkit for running outbound as a solo consultant: score a prospect list, draft a three-touch LinkedIn sequence for each person, log them in Airtable without duplicates, and work out who is due a follow-up and when. Nothing is ever sent automatically; every message is a draft for me to review and send by hand.

Built with Claude Code to my own spec: I set the target profile, the scoring rubric and the three-touch cadence; Claude Code wrote the scripts. The directive/execution layout it sits in comes from Nick Saraev's agent framework.

Separately from this toolkit, discovery conversations I ran directly progressed a proposed $15,000 engagement with an S&P 500 company to contract stage, through seven stakeholder conversations with the CMO as internal champion. It was never signed. That opportunity did not come from this toolkit.

## History: what was verified, and what wasn't

**January–February 2026 (original version, evidence on disk):**
- One full run on 40 attendees of an industry conference produced 120 draft messages (three per person).
- That run had real defects: every lead scored 0/100 because the pipeline read the wrong field from the scorer, and LinkedIn URLs were *guessed* from names (`/in/firstname-lastname`) rather than looked up.
- The only recorded Apollo search returned zero leads.
- How many drafts were actually sent, and what came of them, isn't recorded.

**November 2026 (this version):** I audited the code against those results and against the real structure of my Airtable table (field names and options, read via the metadata API, no lead data), and fixed what was wrong (below). The fixes are covered by 78 automated tests using synthetic leads and a simulated Airtable shaped exactly like the real table. **They have not yet been run against my live Airtable records, the Anthropic API or Apollo.**

| Defect in the original | Fix |
|---|---|
| Scores thrown away (every lead 0/100) | Pipeline reads the scorer's real output field |
| LinkedIn URLs guessed from names | URLs are kept only if the source list supplied a well-formed profile URL; otherwise explicitly marked missing |
| Orchestrator pointed at a file that didn't exist | `--csv` argument; clear error and exit code if the file is missing |
| "Skip if already in Airtable" check never ran | Dedupe on stable identities (profile slug, email, normalised name + company) against every Airtable page and earlier rows in the same run, before any model calls |
| Every write sent a `Company` field the real table doesn't have, which Airtable rejects, so the original pipeline's writes would have failed | Writes include only fields the table actually has (checked once per run via the metadata API) |
| Follow-ups based on status only (anyone "Contacted" was due immediately) | Due only 4 / 10 days after the status last changed, using the table's existing `Days Since Last Progress Update` formula; a blank count is listed separately, never assumed due |
| Only "Replied" stopped a sequence, so "Interested" / "Not Interested" leads kept being chased; Ignore and Call Booked were ignored | Any reply stops the sequence; Ignore and Call Booked leads are never listed |
| Status names disagreed across files ("Nurture" and "Engaged" weren't real options) | One canonical list in `airtable_leads.py` matching the table's real options; unknown values refused before any write |
| `--source apollo` accepted but did nothing | Removed. Apollo is a separate, experimental script (see below) |
| Airtable base ID hard-coded | Moved to `.env` |

## How it fits together

```
Prospect list (CSV) ─► dedupe vs Airtable ─► score ─► draft 3 touches ─► Airtable (Not Contacted)
                                                                              │
              you send Touch 1, set status to Contacted (day count restarts) ◄┘
                                                                              │
                   follow_up_tracker.py ◄── reads Airtable, by day count ─────┘
```

| Script | Job | Status |
|---|---|---|
| `lead_pipeline.py` | CSV → dedupe → score → three drafts → Airtable → copy-paste report | Fixed, tested (synthetic) |
| `lead_scoring.py` | Readable points rubric: title tier, company size, funding, AI-interest keywords, engagement, geography | Unchanged; works as a module |
| `dm_templates.py` | Five message types (connection, value follow-up, soft CTA, lead magnet, re-engagement), each a Claude prompt in my voice | Unchanged; replaced by a fake in tests |
| `airtable_leads.py` | Airtable store and CLI: add, update, status, list, pipeline overview; identity keys; canonical statuses | Rewritten, tested against a simulated Airtable |
| `follow_up_tracker.py` | Lists leads due Touch 2 / Touch 3 by day count; skips replies, Ignore and Call Booked; optional drafts | Rewritten, tested |
| `apollo_lead_search.py` | Standalone Apollo search with its own scoring, writes to `.tmp/` | **Experimental.** Not part of the pipeline; the only recorded run returned zero leads; not re-run |

## Reliability considerations

- Duplicates are checked before spending model calls, and re-running the same list adds nothing.
- If Airtable can't be read, the run stops before drafting or writing anything, because dedupe would be unsafe.
- A failed write or an empty draft marks that lead failed, logs nothing for it and carries on; the next run retries it.
- Still no retry-with-backoff on API calls, and model calls aren't retried.

## Required Airtable fields

| Field | Type |
|---|---|
| `Name`, `LinkedIn URL`, `Role`, `Personalised Message` | Text |
| `Lead Gen Progress` | Single select: Not Contacted, Contacted, Followed Up, Closed |
| `Reply Status` | Single select: No Reply, Replied, Interested, Not Interested |
| `Ignore`, `Call Booked` | Checkbox |
| `Days Since Last Progress Update` | Formula: `IF({Lead Gen Progress}, DATETIME_DIFF(TODAY(), LAST_MODIFIED_TIME({Lead Gen Progress}), 'days'), BLANK())` |
| `Company` | Optional text. Written only if the table has it; without it, dedupe falls back to matching on name |

## Limitations

- Tested only against synthetic data and a simulated Airtable, not my live records.
- The day count restarts whenever the status is changed, so correcting a status by hand also resets the follow-up clock.
- If the Airtable token can't read table metadata, writes include every field, and a missing optional field makes the write fail (reported, not silent).
- LinkedIn URL checks are format-only; a well-formed URL may still belong to the wrong person.
- A list with only name, title and company scores low (the conference list maxes out around 25/100), because most of the rubric needs company size, funding and keyword data.
- The AI-keyword check is substring-based, so it can match "ai" inside unrelated words.
- Two people with the same name at the same company would be treated as one prospect, and when the table stores no company, a new lead with the same name as an existing one is treated as the same person.
- Built for one person's workflow, not a team.
- Two LinkedIn-scraping helpers from my private workspace (one using a logged-in session cookie, one using a third-party scraper) are deliberately not included here.

## Running it

```
cp .env.example .env                                    # add your keys
python3 -m execution.lead_pipeline --csv my_list.csv --no-airtable   # drafts only
python3 -m execution.lead_pipeline --csv my_list.csv -o outreach.md
python3 -m execution.follow_up_tracker
python3 -m pytest                                       # no network or API keys needed
```

The CSV needs a `name` column; `title`, `company`, `linkedin_url`, `email`, `location`, `headline`, `keywords`, `source` and `priority` are optional. No real lead data, account tokens or client-identifying information is included in this repo.
