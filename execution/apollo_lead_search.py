#!/usr/bin/env python3
"""
Apollo.io Lead Search — EXPERIMENTAL, standalone.

Searches Apollo for marketing/growth leaders matching the ICP, scores them with its own
formula, drafts one message each and saves to .tmp/real_leads_apollo.csv/.json. It is
not part of lead_pipeline.py and doesn't write to Airtable.

Status: the only recorded run (25 Jan 2026) returned zero leads, and it has not been
re-run since. Treat any live sourcing claim as unverified.
"""

import os
import json
import csv
import time
import requests
from datetime import datetime
from typing import Dict, List
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


class ApolloLeadSearch:
    # AI-related keywords for identifying warm leads
    AI_KEYWORDS = [
        "artificial intelligence", "AI", "machine learning", "automation",
        "marketing automation", "martech", "digital transformation",
        "marketing technology", "data-driven", "growth hacking"
    ]

    def __init__(self):
        self.api_key = os.getenv('APOLLO_API_KEY')
        if not self.api_key:
            raise ValueError("APOLLO_API_KEY not set in .env")

        self.base_url = "https://api.apollo.io/api/v1"
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "x-api-key": self.api_key
        }

    def search_leads(self, page: int = 1, per_page: int = 25, ai_focused: bool = True) -> Dict:
        """
        Search for CMO/VP Marketing/Head of Growth leads
        Args:
            ai_focused: If True, filter for companies with AI/automation keywords (warm leads)
        """
        url = f"{self.base_url}/mixed_people/search"

        payload = {
            "page": page,
            "per_page": per_page,
            "person_titles": [
                "CMO",
                "Chief Marketing Officer",
                "VP Marketing",
                "VP of Marketing",
                "Vice President Marketing",
                "Vice President of Marketing",
                "Head of Marketing",
                "Head of Growth",
                "VP Growth",
                "VP of Growth",
                "Vice President Growth",
                "Chief Growth Officer",
                "Director of Marketing",
                "Marketing Director"
            ],
            "person_seniorities": ["c_suite", "vp", "director"],
            "organization_num_employees_ranges": ["11,50", "51,200", "201,500", "501,1000", "1001,5000"],
            "person_locations": ["United States", "United Kingdom", "Canada", "Australia"],
            "organization_latest_funding_stage_cd": ["series_a", "series_b", "series_c", "series_d", "series_e"]
        }

        # Add AI-related keyword filter for warm leads
        if ai_focused:
            payload["q_organization_keyword_tags"] = self.AI_KEYWORDS

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error searching leads: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return {"people": [], "pagination": {}}

    def extract_lead_data(self, person: Dict) -> Dict:
        """Extract relevant data from Apollo person record"""

        org = person.get("organization", {}) or {}
        keywords = org.get("keywords", []) or []

        # Calculate warmth score based on AI-readiness signals
        warmth_score = self._calculate_warmth_score(person, org, keywords)

        # Check for AI-interest signals
        ai_signals = self._detect_ai_signals(keywords, person.get("headline", ""))

        return {
            "name": person.get("name", ""),
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", ""),
            "title": person.get("title", ""),
            "company": org.get("name", ""),
            "industry": org.get("industry", ""),
            "company_size": org.get("estimated_num_employees", ""),
            "location": person.get("city", "") + ", " + person.get("country", "") if person.get("city") else person.get("country", ""),
            "linkedin_url": person.get("linkedin_url", ""),
            "company_linkedin": org.get("linkedin_url", ""),
            "company_website": org.get("website_url", ""),
            "funding_stage": org.get("latest_funding_stage", ""),
            "keywords": ", ".join(keywords[:5]) if keywords else "",
            "headline": person.get("headline", ""),
            "warmth_score": warmth_score,
            "ai_signals": ai_signals
        }

    def _calculate_warmth_score(self, person: Dict, org: Dict, keywords: List) -> int:
        """Calculate lead warmth score (0-100) based on qualification criteria"""
        score = 0

        # Title match (CMO/VP/Head) +20
        title = person.get("title", "").lower()
        if any(t in title for t in ["cmo", "chief marketing", "vp", "vice president", "head of"]):
            score += 20

        # Company size 50-500 +15
        size = org.get("estimated_num_employees", 0) or 0
        if 50 <= size <= 500:
            score += 15
        elif 11 <= size < 50 or 500 < size <= 1000:
            score += 10

        # Series A-C funding +15
        funding = org.get("latest_funding_stage", "").lower()
        if any(f in funding for f in ["series_a", "series_b", "series_c", "series a", "series b", "series c"]):
            score += 15

        # AI-related keywords +20
        ai_terms = ["ai", "artificial intelligence", "machine learning", "automation", "martech"]
        keyword_str = " ".join(keywords).lower()
        if any(term in keyword_str for term in ai_terms):
            score += 20

        # Tech stack includes martech +10
        if any(t in keyword_str for t in ["saas", "software", "technology", "digital", "marketing technology"]):
            score += 10

        # Located in target geo +5
        country = person.get("country", "").lower()
        if any(g in country for g in ["united states", "united kingdom", "canada", "australia"]):
            score += 5

        return min(score, 100)

    def _detect_ai_signals(self, keywords: List, headline: str) -> List[str]:
        """Detect AI-interest signals from keywords and headline"""
        signals = []
        combined = " ".join(keywords).lower() + " " + headline.lower()

        signal_map = {
            "AI/ML Interest": ["ai", "artificial intelligence", "machine learning", "ml"],
            "Automation Focus": ["automation", "automated", "automate"],
            "MarTech Savvy": ["martech", "marketing technology", "marketing automation"],
            "Digital Transformation": ["digital transformation", "digitization", "modernization"],
            "Data-Driven": ["data-driven", "analytics", "data science"],
            "Growth Mindset": ["growth", "scale", "scaling", "hypergrowth"]
        }

        for signal_name, terms in signal_map.items():
            if any(term in combined for term in terms):
                signals.append(signal_name)

        return signals


class OutreachGenerator:
    def __init__(self):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-opus-4-5-20251101"

    def generate_dm(self, lead: Dict) -> str:
        """Generate personalized DM for a lead"""

        # Get AI signals if available
        ai_signals = lead.get('ai_signals', [])
        warmth_score = lead.get('warmth_score', 0)

        prompt = f"""Write a LinkedIn connection request note for this prospect. You build done-for-you AI systems for marketing teams - not tools to learn, but custom workflows that run on autopilot.

LEAD INFO:
- Name: {lead['name']} (use first name only)
- Title: {lead['title']}
- Company: {lead['company']}
- Industry: {lead['industry']}
- Company Size: {lead['company_size']} employees
- Funding Stage: {lead['funding_stage']}
- Company Keywords: {lead['keywords']}
- Their Headline: {lead['headline']}
- AI-Interest Signals: {', '.join(ai_signals) if ai_signals else 'None detected'}
- Warmth Score: {warmth_score}/100

YOUR POSITIONING:
- You build done-for-you AI systems for marketing teams
- Not tools to learn, but custom workflows that run on autopilot
- Focus: content creation, lead research, campaign automation

STYLE REQUIREMENTS:
- Start with an observation about THEIR company/industry/role (not "I noticed...")
- Keep it conversational - like a colleague, not a salesperson
- Short sentences. Natural breaks.
- Mention "AI systems" or "workflows that run on autopilot" naturally
- NO "I help companies..." pitches
- NO "quick call?" or obvious CTAs
- Must reference something specific to THIS person
- Under 80 words (connection notes are short)

Return ONLY the connection note text, nothing else."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"Error generating DM for {lead['name']}: {e}")
            return ""


def main():
    print("="*60)
    print("APOLLO LEAD SEARCH - AI-Ready Marketing Executives")
    print("Target: CMO / VP Marketing / Head of Growth")
    print("Focus: Warm leads interested in AI implementation")
    print("="*60)

    apollo = ApolloLeadSearch()
    outreach = OutreachGenerator()

    all_leads = []
    target_leads = 100
    per_page = 25
    page = 1

    print(f"\nSearching for {target_leads}+ AI-ready leads...")
    print(f"Filtering by AI keywords: {', '.join(apollo.AI_KEYWORDS[:5])}...")

    while len(all_leads) < target_leads:
        print(f"\n--- Page {page} ---")

        results = apollo.search_leads(page=page, per_page=per_page)
        people = results.get("people", [])

        if not people:
            print("No more results found")
            break

        print(f"Found {len(people)} leads on this page")

        for person in people:
            lead = apollo.extract_lead_data(person)

            # Skip if no LinkedIn URL
            if not lead['linkedin_url']:
                continue

            # Skip if missing key info
            if not lead['name'] or not lead['company']:
                continue

                warmth = lead.get('warmth_score', 0)
            signals = lead.get('ai_signals', [])
            print(f"  Processing: {lead['name']} - {lead['title']} at {lead['company']}")
            print(f"    Warmth: {warmth}/100 | Signals: {', '.join(signals) if signals else 'None'}")

            # Only process leads with warmth score >= 40 (prioritize warmer leads)
            if warmth < 40:
                print(f"    Skipping (warmth score too low)")
                continue

            # Generate personalized DM
            dm = outreach.generate_dm(lead)
            lead['personalized_dm'] = dm

            # Convert ai_signals list to string for CSV
            lead['ai_signals_str'] = ', '.join(lead.get('ai_signals', []))

            all_leads.append(lead)

            if len(all_leads) >= target_leads:
                break

            # Rate limiting
            time.sleep(0.5)

        page += 1
        time.sleep(1)  # Respect API limits

        if page > 10:  # Safety limit
            break

    # Save to CSV
    csv_path = ".tmp/real_leads_apollo.csv"
    os.makedirs(".tmp", exist_ok=True)

    print(f"\n--- Saving {len(all_leads)} leads to CSV ---")

    fieldnames = [
        'name', 'first_name', 'last_name', 'title', 'company',
        'industry', 'company_size', 'location', 'linkedin_url',
        'company_linkedin', 'company_website', 'funding_stage',
        'keywords', 'headline', 'warmth_score', 'ai_signals_str', 'personalized_dm'
    ]

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_leads)

    # Also save JSON
    json_path = ".tmp/real_leads_apollo.json"
    with open(json_path, 'w') as f:
        json.dump(all_leads, f, indent=2)

    print(f"\n" + "="*60)
    print("COMPLETE!")
    print("="*60)
    print(f"\nPulled {len(all_leads)} leads (LinkedIn URLs as returned by Apollo, not checked)")
    print(f"\nFiles saved:")
    print(f"  CSV: {csv_path}")
    print(f"  JSON: {json_path}")

    if all_leads:
        # Sort by warmth score
        all_leads_sorted = sorted(all_leads, key=lambda x: x.get('warmth_score', 0), reverse=True)

        print(f"\n--- Top 3 Warmest Leads ---")
        for i, sample in enumerate(all_leads_sorted[:3], 1):
            print(f"\n{i}. {sample['name']}")
            print(f"   Title: {sample['title']} at {sample['company']}")
            print(f"   Warmth Score: {sample.get('warmth_score', 0)}/100")
            print(f"   AI Signals: {sample.get('ai_signals_str', 'None')}")
            print(f"   LinkedIn: {sample['linkedin_url']}")
            print(f"   DM: {sample['personalized_dm'][:120]}...")

    return csv_path


if __name__ == '__main__':
    main()
