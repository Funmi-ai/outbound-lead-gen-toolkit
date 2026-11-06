#!/usr/bin/env python3
"""
Lead Scoring Module
Calculates warmth scores for leads based on AI-readiness signals
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class LeadStatus(Enum):
    """Lead pipeline status"""
    NOT_CONTACTED = "Not Contacted"
    CONNECTION_PENDING = "Connection Pending"
    CONTACTED = "Contacted"
    LEAD_MAGNET_SENT = "Lead Magnet Sent"
    ENGAGED = "Engaged"
    CALL_BOOKED = "Call Booked"
    NURTURE = "Nurture"
    DORMANT = "Dormant"
    NOT_INTERESTED = "Not Interested"


@dataclass
class ScoringCriteria:
    """Scoring criteria configuration"""
    # Title scoring
    title_c_suite: int = 25  # CMO, Chief Marketing Officer
    title_vp: int = 20       # VP Marketing, VP Growth
    title_head: int = 20     # Head of Marketing, Head of Growth
    title_director: int = 15 # Director of Marketing

    # Company size scoring
    size_50_500: int = 15    # Sweet spot
    size_11_50: int = 10     # Small but growing
    size_500_1000: int = 10  # Mid-size
    size_1000_plus: int = 5  # Enterprise (slower decisions)

    # Funding stage scoring
    funding_series_a_c: int = 15
    funding_series_d_e: int = 10
    funding_seed: int = 5

    # AI-interest signals
    ai_keywords: int = 20
    martech_stack: int = 10
    digital_transformation: int = 10

    # Engagement signals
    profile_viewed: int = 15
    content_engagement: int = 10
    mutual_connections: int = 5

    # Other signals
    recent_job_change: int = 10  # Within 6 months
    target_geo: int = 5


class LeadScorer:
    """Calculate lead warmth scores based on multiple signals"""

    # AI-related keywords to detect
    AI_KEYWORDS = [
        "ai", "artificial intelligence", "machine learning", "ml",
        "automation", "automated", "automate",
        "martech", "marketing technology", "marketing automation",
        "digital transformation", "digitization",
        "data-driven", "analytics", "data science",
        "growth hacking", "hypergrowth"
    ]

    # Target titles by tier
    TITLE_TIERS = {
        "c_suite": ["cmo", "chief marketing officer", "chief growth officer"],
        "vp": ["vp marketing", "vp of marketing", "vice president marketing",
               "vp growth", "vp of growth", "vice president growth"],
        "head": ["head of marketing", "head of growth"],
        "director": ["director of marketing", "marketing director", "director of growth"]
    }

    # Target geographies
    TARGET_GEOS = ["united states", "united kingdom", "canada", "australia", "usa", "uk"]

    def __init__(self, criteria: Optional[ScoringCriteria] = None):
        self.criteria = criteria or ScoringCriteria()

    def score_lead(self, lead: Dict) -> Dict:
        """
        Calculate comprehensive warmth score for a lead

        Args:
            lead: Dictionary with lead data

        Returns:
            Dictionary with score breakdown and total
        """
        breakdown = {
            "title_score": self._score_title(lead.get("title", "")),
            "company_size_score": self._score_company_size(lead.get("company_size", 0)),
            "funding_score": self._score_funding(lead.get("funding_stage", "")),
            "ai_interest_score": self._score_ai_interest(lead),
            "engagement_score": self._score_engagement(lead),
            "geo_score": self._score_geography(lead.get("location", ""))
        }

        total = sum(breakdown.values())
        breakdown["total_score"] = min(total, 100)
        breakdown["qualification"] = self._get_qualification_tier(breakdown["total_score"])

        return breakdown

    def _score_title(self, title: str) -> int:
        """Score based on job title"""
        title_lower = title.lower()

        for c_suite in self.TITLE_TIERS["c_suite"]:
            if c_suite in title_lower:
                return self.criteria.title_c_suite

        for vp in self.TITLE_TIERS["vp"]:
            if vp in title_lower:
                return self.criteria.title_vp

        for head in self.TITLE_TIERS["head"]:
            if head in title_lower:
                return self.criteria.title_head

        for director in self.TITLE_TIERS["director"]:
            if director in title_lower:
                return self.criteria.title_director

        return 0

    def _score_company_size(self, size) -> int:
        """Score based on company size"""
        try:
            size = int(size) if size else 0
        except (ValueError, TypeError):
            return 0

        if 50 <= size <= 500:
            return self.criteria.size_50_500
        elif 11 <= size < 50:
            return self.criteria.size_11_50
        elif 500 < size <= 1000:
            return self.criteria.size_500_1000
        elif size > 1000:
            return self.criteria.size_1000_plus

        return 0

    def _score_funding(self, funding_stage: str) -> int:
        """Score based on funding stage"""
        funding_lower = funding_stage.lower()

        if any(f in funding_lower for f in ["series_a", "series_b", "series_c", "series a", "series b", "series c"]):
            return self.criteria.funding_series_a_c
        elif any(f in funding_lower for f in ["series_d", "series_e", "series d", "series e"]):
            return self.criteria.funding_series_d_e
        elif "seed" in funding_lower:
            return self.criteria.funding_seed

        return 0

    def _score_ai_interest(self, lead: Dict) -> int:
        """Score based on AI-interest signals"""
        score = 0
        keywords = lead.get("keywords", "").lower()
        headline = lead.get("headline", "").lower()
        combined = keywords + " " + headline

        # AI/ML keywords
        if any(kw in combined for kw in ["ai", "artificial intelligence", "machine learning", "ml"]):
            score += self.criteria.ai_keywords

        # MarTech stack
        if any(kw in combined for kw in ["martech", "marketing technology", "marketing automation", "hubspot", "marketo", "salesforce"]):
            score += self.criteria.martech_stack

        # Digital transformation
        if any(kw in combined for kw in ["digital transformation", "digitization", "modernization"]):
            score += self.criteria.digital_transformation

        return min(score, 40)  # Cap at 40 for this category

    def _score_engagement(self, lead: Dict) -> int:
        """Score based on engagement signals"""
        score = 0

        if lead.get("profile_viewed"):
            score += self.criteria.profile_viewed

        if lead.get("content_engagement"):
            score += self.criteria.content_engagement

        if lead.get("mutual_connections", 0) >= 3:
            score += self.criteria.mutual_connections

        if lead.get("recent_job_change"):
            score += self.criteria.recent_job_change

        return min(score, 30)  # Cap at 30 for this category

    def _score_geography(self, location: str) -> int:
        """Score based on geography"""
        location_lower = location.lower()

        if any(geo in location_lower for geo in self.TARGET_GEOS):
            return self.criteria.target_geo

        return 0

    def _get_qualification_tier(self, score: int) -> str:
        """Get qualification tier based on score"""
        if score >= 70:
            return "hot"       # Immediate outreach
        elif score >= 50:
            return "warm"      # Priority outreach
        elif score >= 30:
            return "cool"      # Standard outreach
        else:
            return "cold"      # Nurture only

    def detect_ai_signals(self, lead: Dict) -> List[str]:
        """Detect specific AI-interest signals"""
        signals = []
        keywords = lead.get("keywords", "").lower()
        headline = lead.get("headline", "").lower()
        combined = keywords + " " + headline

        signal_map = {
            "AI/ML Interest": ["ai", "artificial intelligence", "machine learning", "ml"],
            "Automation Focus": ["automation", "automated", "automate"],
            "MarTech Savvy": ["martech", "marketing technology", "marketing automation", "hubspot", "marketo"],
            "Digital Transformation": ["digital transformation", "digitization", "modernization"],
            "Data-Driven": ["data-driven", "analytics", "data science"],
            "Growth Mindset": ["growth", "scale", "scaling", "hypergrowth"],
            "SaaS/Tech": ["saas", "software", "technology", "tech"]
        }

        for signal_name, terms in signal_map.items():
            if any(term in combined for term in terms):
                signals.append(signal_name)

        return signals

    def prioritize_leads(self, leads: List[Dict]) -> List[Dict]:
        """
        Score and prioritize a list of leads

        Returns leads sorted by warmth score (highest first)
        """
        scored_leads = []

        for lead in leads:
            score_breakdown = self.score_lead(lead)
            lead["warmth_score"] = score_breakdown["total_score"]
            lead["qualification"] = score_breakdown["qualification"]
            lead["score_breakdown"] = score_breakdown
            lead["ai_signals"] = self.detect_ai_signals(lead)
            scored_leads.append(lead)

        # Sort by warmth score descending
        return sorted(scored_leads, key=lambda x: x["warmth_score"], reverse=True)

    def filter_warm_leads(self, leads: List[Dict], min_score: int = 50) -> List[Dict]:
        """Filter leads by minimum warmth score"""
        scored_leads = self.prioritize_leads(leads)
        return [lead for lead in scored_leads if lead["warmth_score"] >= min_score]


def main():
    """Test the lead scoring module"""
    scorer = LeadScorer()

    # Sample leads for testing
    test_leads = [
        {
            "name": "Sarah Johnson",
            "title": "CMO",
            "company": "TechCorp",
            "company_size": 250,
            "funding_stage": "Series B",
            "keywords": "AI, marketing automation, SaaS",
            "headline": "CMO driving digital transformation",
            "location": "San Francisco, United States"
        },
        {
            "name": "Mike Chen",
            "title": "VP of Marketing",
            "company": "GrowthStartup",
            "company_size": 75,
            "funding_stage": "Series A",
            "keywords": "growth hacking, data-driven",
            "headline": "Building scalable marketing engines",
            "location": "New York, United States"
        },
        {
            "name": "Emma Wilson",
            "title": "Marketing Manager",
            "company": "SmallBiz",
            "company_size": 25,
            "funding_stage": "Seed",
            "keywords": "social media, content",
            "headline": "Marketing enthusiast",
            "location": "London, United Kingdom"
        }
    ]

    print("="*60)
    print("LEAD SCORING TEST")
    print("="*60)

    prioritized = scorer.prioritize_leads(test_leads)

    for lead in prioritized:
        print(f"\n{lead['name']} - {lead['title']}")
        print(f"  Company: {lead['company']} ({lead['company_size']} employees)")
        print(f"  Warmth Score: {lead['warmth_score']}/100 ({lead['qualification'].upper()})")
        print(f"  AI Signals: {', '.join(lead['ai_signals']) or 'None'}")
        print(f"  Score Breakdown:")
        for key, value in lead['score_breakdown'].items():
            if key not in ['total_score', 'qualification']:
                print(f"    - {key}: {value}")


if __name__ == "__main__":
    main()
