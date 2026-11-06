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

**November 2026 (this version):** I audited the code against those results and fixed what was wrong (below). The fixes are covered by 62 automated tests using synthetic leads and a simulated Airtable. **They have not yet been run against my live Airtable base, the Anthropic API or Apollo.**

| Defect in the original | Fix |
|---|---|
| Scores thrown away (every lead 0/100) | Pipeline reads the scorer's real output field |
| LinkedIn URLs guessed from names | URLs are kept only if the source list supplied a well-formed profile URL; otherwise explicitly marked missing |
| Orchestrator pointed at a file that didn't exist | `--csv` argument; clear error and exit code if the file is missing |
| "Skip if already in Airtable" check never ran | Dedupe on stable identities (profile slug, email, normalised name + company) against every Airtable page and earlier rows in the same run, before any model calls |
| Follow-ups based on status only (anyone "Contacted" was due immediately) | Due only after 4 / 10 / 30 days since **Last Contacted**; leads with no date are listed separately, never assumed due |
| Status names disagreed across files | One canonical list in `airtable_leads.py`; unknown values refused before any write |
| `--source apollo` accepted but did nothing | Removed. Apollo is a separate, experimental script (see below) |
| Airtable base ID hard-coded | Moved to `.env` |

## How it fits together

```
Prospect list (CSV) ─► dedupe vs Airtable ─► score ─► draft 3 touches ─► Airtable (Not Contacted)
                                                                              │
                     you send Touch 1, mark Contacted (stamps Last Contacted) ◄┘
                                                                              │
                          follow_up_tracker.py ◄── reads Airtable, by date ───┘
```

| Script | Job | Status |
|---|---|---|
| `lead_pipeline.py` | CSV → dedupe → score → three drafts → Airtable → copy-paste report | Fixed, tested (synthetic) |
| `lead_scoring.py` | Readable points rubric: title tier, company size, funding, AI-interest keywords, engagement, geography | Unchanged; works as a module |
| `dm_templates.py` | Five message types (connection, value follow-up, soft CTA, lead magnet, re-engagement), each a Claude prompt in my voice | Unchanged; replaced by a fake in tests |
| `airtable_leads.py` | Airtable store and CLI: add, update, status, list, pipeline overview; identity keys; canonical statuses | Rewritten, tested against a simulated Airtable |
| `follow_up_tracker.py` | Lists leads due Touch 2 / Touch 3 / re-engagement by date; optional drafts | Rewritten, tested |
| `apollo_lead_search.py` | Standalone Apollo search with its own scoring, writes to `.tmp/` | **Experimental.** Not part of the pipeline; the only recorded run returned zero leads; not re-run |

## Reliability considerations

- Duplicates are checked before spending model calls, and re-running the same list adds nothing.
- If Airtable can't be read, the run stops before drafting or writing anything, because dedupe would be unsafe.
- A failed write or an empty draft marks that lead failed, logs nothing for it and carries on; the next run retries it.
- Still no retry-with-backoff on API calls, and model calls aren't retried.

## Required Airtable fields

`Name`, `LinkedIn URL`, `Company`, `Role`, `Personalised Message`, `Lead Gen Progress` (single select: Not Contacted, Contacted, Followed Up, Nurture, Closed), `Reply Status` (single select: No Reply, Replied), `Last Contacted` (date).

## Limitations

- Tested only against synthetic data and a simulated Airtable, not my live base.
- LinkedIn URL checks are format-only; a well-formed URL may still belong to the wrong person.
- A list with only name, title and company scores low (the conference list maxes out around 25/100), because most of the rubric needs company size, funding and keyword data.
- The AI-keyword check is substring-based, so it can match "ai" inside unrelated words.
- Two people with the same name at the same company would be treated as one prospect.
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
