"""Background web research via DuckDuckGo.

For each video idea, runs the LLM-suggested search queries and attaches
top results as background_research on the idea object.
"""

from __future__ import annotations

from ddgs import DDGS


def research_topic(query: str, max_results: int = 3) -> list[dict]:
    results: list[dict] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                }
            )
    return results


def enrich_ideas_with_research(ideas: list[dict], max_queries: int) -> list[dict]:
    enriched = []
    for idea in ideas:
        queries = idea.get("research_queries", [])[:max_queries]
        research = []
        for query in queries:
            try:
                hits = research_topic(query, max_results=2)
                research.append({"query": query, "results": hits})
            except Exception as exc:
                research.append({"query": query, "error": str(exc)})
        idea = {**idea, "background_research": research}
        enriched.append(idea)
    return enriched
