"""
AI orchestration service.
Phase 1: Decompose user description into Tavily search queries.
Phase 2: Run Tavily searches and build research corpus.
Phase 3: Call Claude Opus 4.6 to generate structured proposal content.
"""

import os
import json
import asyncio
from typing import Optional, Callable
import anthropic
from tavily import TavilyClient

from models.generation import ProposalContent

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """You are a Senior Policy Advisor and Applied Economist at Pahle India Foundation, \
a leading public policy think tank based in New Delhi. You write rigorous, evidence-based research \
proposals for policy audiences including government ministries, regulators, multilateral organisations, \
and development finance institutions.

Your writing conventions:
- Indian English: colour, analyse, programme, lakh, crore, per cent (not percent)
- Formal, authoritative register — avoid casual phrasing
- Cite data with vintage (year/quarter) and source explicitly (e.g., "RBI Annual Report 2023-24")
- Distinguish correlation from causation clearly
- State policy implications explicitly — connect analysis to actionable recommendations
- Economic and statistical terminology used precisely
- Proposals follow: Problem Statement → Policy Context → Evidence Review → Proposed Intervention → M&E Framework → Budget Indicatives"""

PROPOSAL_JSON_SCHEMA = """{
  "title": "string — concise research proposal title",
  "subtitle": "string — one-line subtitle",
  "authors": "string — e.g. 'Research Team, Pahle India Foundation'",
  "executive_summary": "string — 200-300 words summarising the proposal",
  "problem_statement": "string — 300-500 words with data citations",
  "policy_context": "string — 300-400 words on the regulatory/policy landscape",
  "objectives": [{"number": 1, "text": "string"}],
  "methodology": "string — 400-600 words covering methods, datasets, quality controls",
  "results": [{"heading": "string", "content": "string (150-250 words)", "data_point": "string — key stat for PPT"}],
  "takeaways": [{"number": 1, "actor": "Ministry/regulator/entity name", "recommendation": "string — actionable recommendation"}],
  "conclusion": "string — 150-200 words: the so-what, urgency, immediate next step",
  "glossary": [{"term": "string", "definition": "string"}],
  "annexures": "string or null",
  "sources": [{"title": "string", "url": "string", "date": "string"}],
  "ppt_slides": [
    {
      "slide_number": 1,
      "slide_type": "title",
      "title": "string",
      "subtitle": "string or null",
      "body_points": [],
      "data_callout": "string or null"
    }
  ]
}"""

PPT_SLIDE_INSTRUCTIONS = """
The ppt_slides array must contain exactly 13 slides in this order:
1.  slide_type="title"          — Title slide: title=proposal title, subtitle=subtitle + authors
2.  slide_type="content"        — Agenda: body_points=list of section names
3.  slide_type="content"        — Problem Statement: 4-5 body_points + data_callout with key stat
4.  slide_type="content"        — Policy Context: 4-5 body_points
5.  slide_type="content"        — Objectives: list each objective as a body_point
6.  slide_type="content"        — Methodology: 4-5 body_points
7.  slide_type="content"        — Finding 1: title=first result heading, body_points + data_callout
8.  slide_type="content"        — Finding 2: title=second result heading (if exists)
9.  slide_type="content"        — Finding 3: title=third result heading (if exists)
10. slide_type="content"        — Takeaways & Recommendations: one body_point per takeaway
11. slide_type="content"        — M&E Framework: 4-5 body_points on monitoring and evaluation
12. slide_type="content"        — Conclusion: 3-4 body_points + data_callout
13. slide_type="thank_you"      — Thank you slide: title="Thank You", subtitle=contact line
"""


class AIService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.tavily = TavilyClient(api_key=TAVILY_API_KEY)

    async def decompose(self, description: str, feedback: Optional[str] = None) -> dict:
        """Extract title and search queries from user description."""
        user_content = f"RESEARCHER BRIEF:\n{description}"
        if feedback:
            user_content += f"\n\nFEEDBACK FOR REVISION:\n{feedback}"

        prompt = f"""{user_content}

Based on the above, return a JSON object with exactly these keys:
{{
  "title": "concise research proposal title",
  "domain": "primary policy domain (e.g. taxation, health, agriculture)",
  "queries": ["query1", "query2", "query3", "query4", "query5", "query6"]
}}

The queries array must have 5-8 search queries optimised for finding Indian government data, \
policy reports, and academic research relevant to this proposal. Include queries targeting \
sources like RBI, MoSPI, NITI Aayog, World Bank India, IMF India, and relevant ministries. \
Return ONLY the JSON object, no other text."""

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    async def research(self, queries: list[str], progress_callback: Optional[Callable] = None) -> str:
        """Run Tavily searches and return a formatted research corpus string."""
        all_results = []
        preferred_domains = [
            "gov.in", "rbi.org.in", "mospi.gov.in", "niti.gov.in",
            "worldbank.org", "imf.org", "oecd.org", "jstor.org", "papers.ssrn.com"
        ]

        loop = asyncio.get_event_loop()
        for query in queries:
            if progress_callback:
                progress_callback(query)
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda q=query: self.tavily.search(
                        query=q,
                        search_depth="advanced",
                        max_results=5,
                        include_raw_content=False,
                    )
                )
                results = result.get("results", [])
                # Prefer authoritative sources
                results.sort(
                    key=lambda r: any(d in r.get("url", "") for d in preferred_domains),
                    reverse=True
                )
                all_results.append({"query": query, "results": results[:5]})
            except Exception:
                pass

        # Format into a readable corpus
        corpus_parts = []
        for item in all_results:
            corpus_parts.append(f"\n=== Search: {item['query']} ===")
            for r in item["results"]:
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                content = r.get("content", "")[:600]
                published = r.get("published_date", "")
                corpus_parts.append(f"\nSOURCE: {title}\nURL: {url}\nDate: {published}\n{content}")

        return "\n".join(corpus_parts)

    async def generate(self, description: str, research_corpus: str, feedback: Optional[str] = None) -> ProposalContent:
        """Generate full proposal content using Claude Opus 4.6."""
        user_content = f"""RESEARCHER BRIEF:
{description}
"""
        if feedback:
            user_content += f"""
FEEDBACK FOR THIS REVISION (pay close attention to this):
{feedback}
"""
        user_content += f"""
WEB RESEARCH CORPUS (use data and sources from here wherever possible):
{research_corpus}

TASK:
Generate a complete, high-quality research proposal for Pahle India Foundation.
Return ONLY a valid JSON object exactly matching this schema:
{PROPOSAL_JSON_SCHEMA}

IMPORTANT CONSTRAINTS:
- results array must have 3-4 items
- takeaways array must have exactly 3-5 items with specific actor names (ministry/regulator/entity)
- objectives array must have 4-6 items
- glossary must have 5-10 relevant technical terms
- sources must include all URLs cited from the research corpus
- All monetary figures in Indian context must use lakh/crore (not million/billion)
{PPT_SLIDE_INSTRUCTIONS}
Return ONLY the JSON object. No markdown, no explanation, no code fences."""

        loop = asyncio.get_event_loop()

        async def _call():
            return await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=MODEL,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
            )

        response = await _call()
        text = response.content[0].text.strip()

        # Strip any markdown code fences
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        try:
            data = json.loads(text)
            return ProposalContent(**data)
        except Exception as e:
            # One retry: send the error back to Claude
            retry_prompt = f"""The JSON you returned had a validation error: {e}

Please return a corrected JSON object matching the schema exactly. Return ONLY the JSON, no other text."""
            response2 = await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    model=MODEL,
                    max_tokens=8192,
                    system=SYSTEM_PROMPT,
                    messages=[
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": retry_prompt},
                    ],
                )
            )
            text2 = response2.content[0].text.strip()
            if text2.startswith("```"):
                parts = text2.split("```")
                text2 = parts[1]
                if text2.startswith("json"):
                    text2 = text2[4:]
            data2 = json.loads(text2.strip())
            return ProposalContent(**data2)
