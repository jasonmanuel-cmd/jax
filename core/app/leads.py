"""Real estate lead finder — searches public data for distressed sellers.

Finds people with foreclosures, tax liens, bankruptcies, or other distress
signals who may need to sell their property quickly.
"""
import re
import asyncio
import httpx
from typing import Optional


class LeadFinder:
    """Search public web data for motivated real estate sellers."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    SEARCH_TEMPLATES = {
        "foreclosure": [
            '"{location}" foreclosure "for sale" -site:zillow.com -site:realtor.com',
            '"{location}" "notice of default" OR "lis pendens" property 2024 OR 2025',
            'site:hudhomestore.com {city}',
        ],
        "pre_foreclosure": [
            '"{location}" pre-foreclosure "must sell" OR "motivated" OR "as-is"',
            '"{location}" "lis pendens" house OR property site:.gov OR site:.us',
            '"{location}" pre-foreclosure listing 2024 OR 2025',
        ],
        "tax_lien": [
            '"{location}" "tax delinquent" property list 2024 OR 2025',
            '"{location}" county "tax lien sale" OR "tax deed sale" properties',
            '"{location}" "unpaid taxes" property auction list',
        ],
        "bankruptcy": [
            '"{location}" chapter 7 OR chapter 13 bankruptcy "real estate" seller',
            'PACER "{location}" bankruptcy real property 2024 OR 2025',
        ],
        "distressed": [
            '"{location}" "must sell" OR "below market" OR "as-is" house 2024 2025',
            '"{location}" "cash offer" OR "sell fast" "foreclosure" OR "divorce" OR "estate sale"',
            '"{location}" "we buy houses" leads foreclosure seller',
        ],
    }

    PUBLIC_SOURCES = [
        "https://www.hudhomestore.gov/Home/Index.aspx",
        "https://homepath.fanniemae.com/",
        "https://homesteps.com/",
    ]

    async def search(
        self,
        location: str,
        search_type: str = "foreclosure",
        limit: int = 20,
    ) -> dict:
        """
        Search for distressed seller leads.

        Returns a dict with:
          - results: list of raw web results
          - sources_checked: list of source URLs searched
          - search_type: what kind of distress was searched
          - location: the target area
        """
        city = location.split(",")[0].strip()
        templates = self.SEARCH_TEMPLATES.get(search_type, self.SEARCH_TEMPLATES["foreclosure"])
        queries = [t.format(location=location, city=city) for t in templates]

        raw_results: list[dict] = []
        sources_checked: list[str] = []

        async with httpx.AsyncClient(
            timeout=20.0,
            headers=self.HEADERS,
            follow_redirects=True,
        ) as client:
            # Run all queries concurrently
            tasks = [self._ddg_search(client, q) for q in queries]
            batches = await asyncio.gather(*tasks, return_exceptions=True)
            for batch in batches:
                if isinstance(batch, list):
                    raw_results.extend(batch)

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[dict] = []
        for r in raw_results:
            key = r.get("url", "")
            if key and key not in seen:
                seen.add(key)
                unique.append(r)

        return {
            "location": location,
            "search_type": search_type,
            "results": unique[:limit],
            "total_found": len(unique),
            "sources_checked": [f"DuckDuckGo: {q[:80]}" for q in queries],
            "public_data_sources": self.PUBLIC_SOURCES,
        }

    async def _ddg_search(self, client: httpx.AsyncClient, query: str) -> list[dict]:
        """POST to DuckDuckGo HTML endpoint and parse results."""
        try:
            r = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": "", "kl": "us-en"},
                headers={**self.HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return self._parse_ddg_html(r.text, query)
        except Exception:
            return []

    def _parse_ddg_html(self, html: str, query: str) -> list[dict]:
        """Extract search results from DuckDuckGo HTML response."""
        results = []

        # DDG HTML structure:
        # <h2 class="result__title"><a class="result__a" href="URL">TITLE</a></h2>
        # <a class="result__snippet">SNIPPET</a>

        # Find all result blocks
        result_blocks = html.split('class="result__title"')
        for block in result_blocks[1:]:  # skip text before first result
            # Extract link
            href_match = re.search(r'href="([^"]+)"', block[:500])
            if not href_match:
                continue
            url = href_match.group(1)
            # Skip DDG internal links
            if "duckduckgo" in url.lower() or url.startswith("/"):
                continue

            # Extract title
            title_match = re.search(r'>(.*?)</a>', block[:500], re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

            # Extract snippet from following text
            snippet = ""
            snip_match = re.search(r'result__snippet[^>]*>(.*?)</a>', block[:2000], re.DOTALL)
            if snip_match:
                snippet = re.sub(r"<[^>]+>", "", snip_match.group(1)).strip()

            if title:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "query": query,
                })

        return results[:8]

    def build_lead_prompt(self, location: str, results: list[dict], search_type: str) -> str:
        """Build a prompt for the LLM to extract structured leads from raw search results."""
        snippets = "\n\n".join(
            f"[{i+1}] {r['title']}\n{r['url']}\n{r['snippet']}"
            for i, r in enumerate(results[:12])
        )
        return f"""You are JAX, a real estate lead intelligence system.

TASK: From the following web search results about distressed properties in {location}, extract any actionable lead information.

SEARCH TYPE: {search_type.replace('_', ' ').title()}

RESULTS:
{snippets}

For each result that contains real property lead data, extract:
- Property address (if mentioned)
- Owner name (if mentioned)
- Situation type (foreclosure / pre-foreclosure / tax lien / bankruptcy / motivated seller / REO / etc.)
- Any contact info mentioned
- Why this could be a good deal
- Source URL

If no specific lead data is found, summarize what resources were found and how the user can find leads there.

Also provide:
1. The best 3 specific action steps Jason can take RIGHT NOW to find {search_type.replace('_',' ')} leads in {location}
2. Which public records websites to check for {location}
3. What to search on Google to find more

Be direct and actionable. This is for real estate investing — finding people who NEED to sell fast."""
