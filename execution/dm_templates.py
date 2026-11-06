#!/usr/bin/env python3
"""
LinkedIn DM Templates & Sequence Management
3-Touch Cadence for AI-Ready Marketing Executives
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


class TouchType(Enum):
    """Types of DM touches in the sequence"""
    CONNECTION_REQUEST = "connection_request"  # Touch 1
    VALUE_FOLLOW_UP = "value_follow_up"        # Touch 2
    SOFT_CTA = "soft_cta"                      # Touch 3
    LEAD_MAGNET = "lead_magnet"                # Optional
    RE_ENGAGEMENT = "re_engagement"            # For dormant leads


@dataclass
class DMTemplate:
    """DM template structure"""
    touch_type: TouchType
    name: str
    prompt_template: str
    max_words: int
    timing_days: int  # Days after previous touch


class DMSequenceManager:
    """Manage LinkedIn DM sequences with AI-powered personalization"""

    def __init__(self):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-opus-4-5-20251101"
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[TouchType, DMTemplate]:
        """Load DM templates for each touch in the sequence"""

        templates = {
            TouchType.CONNECTION_REQUEST: DMTemplate(
                touch_type=TouchType.CONNECTION_REQUEST,
                name="Connection Request Note",
                max_words=100,
                timing_days=0,
                prompt_template="""Write a LinkedIn connection request note in Fattima Mahdi's voice.

FATTIMA'S VOICE:
- Opens with honesty + parenthetical softener like "(and probably shouldn't lead with this)" or "(on paper)"
- Acknowledges the awkwardness of cold outreach
- Frames her work through insight, not pitch
- Ends with permission (it's okay to say no)
- Flowing sentences, not short and choppy
- Her approved DM energy: "I'll be honest (and probably shouldn't lead with this), your profile doesn't give me much to go on. But I've learned that the most interesting people rarely spell themselves out online."

HARD NOs (never use):
- "curious" or "I'm curious"
- "no pitch here"
- "actually" (e.g., "actually work", "actually matter")
- "unlock", "game-changer", "ship", "forge"
- Heavy em-dashes
- Super short robotic sentences back to back
- "It's not X, it's Y" contrasts

CONTEXT:
- Fattima runs an AI agency building done-for-you AI systems for marketing teams
- Not tools to learn, but custom workflows that run on autopilot
- Focus: content creation, lead research, campaign automation

LEAD INFO:
{lead_info}

APPROACH:
- Be honest about not knowing much about them (if true)
- Frame it as wanting to understand what's slowing them down vs what they think is slowing them down
- End with permission: "Sometimes the answer is no, and that's fine too" energy
- Under {max_words} words

Return ONLY the connection note text."""
            ),

            TouchType.VALUE_FOLLOW_UP: DMTemplate(
                touch_type=TouchType.VALUE_FOLLOW_UP,
                name="Value-First Follow-Up",
                max_words=100,
                timing_days=4,  # 3-5 days after connection
                prompt_template="""Write a follow-up LinkedIn DM in Fattima Mahdi's voice after they accepted the connection.

FATTIMA'S VOICE:
- Flowing sentences, not choppy
- Parenthetical softeners like "(which is probably the wrong question to ask)" or "(and this is where it gets interesting)"
- Frames questions through insight: "what's slowing you down vs what you think is slowing you down"
- Permission-giving energy
- Her pattern: observation → question → offer to share

HARD NOs:
- "curious" or "I'm curious"
- "unlock", "game-changer", "ship"
- "actually" (e.g., "actually helps")
- Super short sentences back to back
- "no pitch here"

CONTEXT:
- Fattima runs an AI agency building done-for-you systems
- She wants to understand the gap between what's slowing them down vs what they THINK is slowing them down

LEAD INFO:
{lead_info}

PREVIOUS INTERACTION:
- They accepted your connection request

APPROACH:
- Brief thanks for connecting
- Ask what's taking up most of their time (not "what's your biggest challenge" - too cliche)
- Offer to share what's working for similar teams IF relevant
- End with permission: "Sometimes the gap between 'busy' and 'stuck' is smaller than people think"
- Under {max_words} words

Return ONLY the DM text."""
            ),

            TouchType.SOFT_CTA: DMTemplate(
                touch_type=TouchType.SOFT_CTA,
                name="Soft CTA",
                max_words=120,
                timing_days=7,  # 7-10 days after Touch 2
                prompt_template="""Write a third LinkedIn DM in Fattima Mahdi's voice with a soft call-to-action.

FATTIMA'S VOICE:
- Story → wisdom structure
- Specific details ground the message (not vague)
- Vivid analogy if possible from universal experience
- Ends with permission and wisdom landing
- Flowing sentences, parenthetical softeners
- "Do it anyway" energy - she acts on the quiet voice, not the loud one

HARD NOs:
- "curious" or "I'm curious"
- "unlock", "game-changer", "ship", "forge"
- "actually" (e.g., "actually work")
- "no pitch here"
- Super short robotic sentences
- "It's not X, it's Y" contrasts

CONTEXT:
- Fattima builds done-for-you AI systems
- Recent example: content repurposing engine that turns 1 podcast into 30 pieces automatically
- Takes ~2 weeks to implement, runs without their team touching it

LEAD INFO:
{lead_info}

PREVIOUS INTERACTIONS:
- They accepted connection
- You asked about what's taking up their time
- They may or may not have replied

APPROACH:
- Reference something specific to their situation or industry
- Share a real example with concrete outcome
- Offer a short call to show how it works
- End with: "If it's not the right time, that's completely fine. Sometimes the best move is doing nothing." (her permission-giving energy)
- Under {max_words} words

Return ONLY the DM text."""
            ),

            TouchType.LEAD_MAGNET: DMTemplate(
                touch_type=TouchType.LEAD_MAGNET,
                name="Lead Magnet Share",
                max_words=80,
                timing_days=0,  # Send when appropriate
                prompt_template="""Write a DM offering a relevant lead magnet.

LEAD INFO:
{lead_info}

LEAD MAGNET:
{lead_magnet_info}

STYLE:
- Connect the lead magnet to their specific situation
- Explain what they'll get (specific outcome)
- No pitch, just genuine value share
- Under {max_words} words

Return ONLY the DM text."""
            ),

            TouchType.RE_ENGAGEMENT: DMTemplate(
                touch_type=TouchType.RE_ENGAGEMENT,
                name="Re-engagement",
                max_words=60,
                timing_days=30,  # 30 days after going dormant
                prompt_template="""Write a re-engagement DM for someone who went quiet.

LEAD INFO:
{lead_info}

CONTEXT:
- You connected 30+ days ago
- They didn't respond to previous messages
- You want to stay on their radar without being pushy

STYLE:
- Reference something current (industry news, new capability, recent win)
- Keep it super short and light
- No pressure, just staying visible
- Under {max_words} words

Return ONLY the DM text."""
            )
        }

        return templates

    def generate_dm(self, lead: Dict, touch_type: TouchType, extra_context: Optional[Dict] = None) -> str:
        """
        Generate a personalized DM for a specific touch in the sequence

        Args:
            lead: Lead data dictionary
            touch_type: Type of DM to generate
            extra_context: Optional additional context (e.g., lead magnet info)

        Returns:
            Generated DM text
        """
        template = self.templates.get(touch_type)
        if not template:
            raise ValueError(f"Unknown touch type: {touch_type}")

        # Format lead info
        lead_info = self._format_lead_info(lead)

        # Build prompt
        prompt = template.prompt_template.format(
            lead_info=lead_info,
            max_words=template.max_words,
            lead_magnet_info=extra_context.get("lead_magnet", "") if extra_context else ""
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"Error generating DM: {e}")
            return ""

    def _format_lead_info(self, lead: Dict) -> str:
        """Format lead data for prompt injection"""
        ai_signals = lead.get("ai_signals", [])
        if isinstance(ai_signals, list):
            ai_signals_str = ", ".join(ai_signals) if ai_signals else "None detected"
        else:
            ai_signals_str = ai_signals or "None detected"

        return f"""- Name: {lead.get('first_name', lead.get('name', '').split()[0])}
- Full Name: {lead.get('name', '')}
- Title: {lead.get('title', '')}
- Company: {lead.get('company', '')}
- Industry: {lead.get('industry', '')}
- Company Size: {lead.get('company_size', '')} employees
- Funding Stage: {lead.get('funding_stage', '')}
- Company Keywords: {lead.get('keywords', '')}
- Headline: {lead.get('headline', '')}
- AI Signals: {ai_signals_str}
- Warmth Score: {lead.get('warmth_score', 0)}/100"""

    def generate_full_sequence(self, lead: Dict) -> Dict[str, str]:
        """
        Generate all 3 touches for a lead

        Returns:
            Dictionary with all DMs in the sequence
        """
        sequence = {}

        for touch_type in [TouchType.CONNECTION_REQUEST, TouchType.VALUE_FOLLOW_UP, TouchType.SOFT_CTA]:
            template = self.templates[touch_type]
            dm = self.generate_dm(lead, touch_type)
            sequence[touch_type.value] = {
                "name": template.name,
                "message": dm,
                "timing_days": template.timing_days,
                "max_words": template.max_words
            }

        return sequence

    def get_timing_schedule(self) -> List[Dict]:
        """Get the timing schedule for the DM sequence"""
        schedule = []
        for touch_type in [TouchType.CONNECTION_REQUEST, TouchType.VALUE_FOLLOW_UP, TouchType.SOFT_CTA]:
            template = self.templates[touch_type]
            schedule.append({
                "touch": touch_type.value,
                "name": template.name,
                "day": template.timing_days,
                "description": f"Day {template.timing_days}: {template.name}"
            })
        return schedule


# Lead magnet configurations for quick reference
LEAD_MAGNETS = {
    "ai_readiness": {
        "name": "AI Readiness Scorecard",
        "file": "ai-readiness-scorecard-notion.md",
        "description": "15-minute assessment to identify AI opportunities in your marketing stack",
        "best_for": ["CMO", "Head of Marketing", "VP Marketing"]
    },
    "content_repurposer": {
        "name": "Content Repurposing System",
        "file": "content-repurposer-notion.md",
        "description": "Turn 1 piece of content into 10+ assets automatically",
        "best_for": ["Head of Marketing", "Content Director", "Marketing Director"]
    },
    "roi_translator": {
        "name": "Marketing ROI Translator",
        "file": "marketing-roi-translator-notion.md",
        "description": "Translate marketing metrics into CFO-friendly language",
        "best_for": ["CMO", "VP Marketing", "Head of Marketing"]
    },
    "campaign_reviewer": {
        "name": "Campaign Brief Reviewer",
        "file": "campaign-brief-reviewer-notion.md",
        "description": "AI-powered campaign brief analysis in 60 seconds",
        "best_for": ["Marketing Director", "Campaign Manager", "Head of Growth"]
    }
}


def get_recommended_lead_magnet(lead: Dict) -> Optional[Dict]:
    """
    Recommend the best lead magnet based on lead's role and signals

    Args:
        lead: Lead data dictionary

    Returns:
        Recommended lead magnet config or None
    """
    title = lead.get("title", "").lower()
    ai_signals = lead.get("ai_signals", [])

    # CMO/C-suite - ROI focused
    if any(t in title for t in ["cmo", "chief marketing"]):
        return LEAD_MAGNETS["roi_translator"]

    # VP/Head with AI interest - Readiness scorecard
    if any(t in title for t in ["vp", "head"]):
        if "AI/ML Interest" in ai_signals or "Automation Focus" in ai_signals:
            return LEAD_MAGNETS["ai_readiness"]
        return LEAD_MAGNETS["content_repurposer"]

    # Director level - Tactical tools
    if "director" in title:
        return LEAD_MAGNETS["campaign_reviewer"]

    # Default
    return LEAD_MAGNETS["content_repurposer"]


def main():
    """Test the DM sequence manager"""
    manager = DMSequenceManager()

    # Sample lead
    test_lead = {
        "name": "Sarah Johnson",
        "first_name": "Sarah",
        "title": "CMO",
        "company": "TechCorp",
        "industry": "SaaS",
        "company_size": 250,
        "funding_stage": "Series B",
        "keywords": "AI, marketing automation, SaaS",
        "headline": "CMO driving digital transformation at TechCorp",
        "warmth_score": 85,
        "ai_signals": ["AI/ML Interest", "Automation Focus", "MarTech Savvy"]
    }

    print("="*60)
    print("DM SEQUENCE GENERATOR TEST")
    print("="*60)
    print(f"\nLead: {test_lead['name']} - {test_lead['title']} at {test_lead['company']}")
    print(f"Warmth Score: {test_lead['warmth_score']}/100")
    print(f"AI Signals: {', '.join(test_lead['ai_signals'])}")

    print("\n" + "-"*60)
    print("TIMING SCHEDULE:")
    print("-"*60)
    for item in manager.get_timing_schedule():
        print(f"  {item['description']}")

    print("\n" + "-"*60)
    print("GENERATING FULL SEQUENCE...")
    print("-"*60)

    sequence = manager.generate_full_sequence(test_lead)

    for touch_key, touch_data in sequence.items():
        print(f"\n--- {touch_data['name']} (Day {touch_data['timing_days']}) ---")
        print(touch_data['message'])

    print("\n" + "-"*60)
    print("RECOMMENDED LEAD MAGNET:")
    print("-"*60)
    magnet = get_recommended_lead_magnet(test_lead)
    if magnet:
        print(f"  Name: {magnet['name']}")
        print(f"  Description: {magnet['description']}")
        print(f"  Best for: {', '.join(magnet['best_for'])}")


if __name__ == "__main__":
    main()
