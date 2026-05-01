"""
Research Sub-Agent — Auto-fills product details from a URL.

THINK:   Determine what kind of page this is (product page, landing page, etc.)
ACT:     Fetch the page, extract clean text, call Claude to structure product data.
OBSERVE: Return a structured dict ready to pre-fill the form / ProductInput.

This is a standalone sub-agent called BEFORE script generation.
It does NOT modify ReelJob — it returns raw product data for the user to review.
"""
import json
import re
from typing import Optional
from urllib.parse import urlparse

import anthropic

from config import ANTHROPIC_API_KEY

_MODEL = "claude-haiku-4-5"   # Fast + cheap for extraction — no need for Sonnet

_SYSTEM_PROMPT = """\
You are a product data extraction specialist. Given raw webpage text from a product or
landing page, extract structured product information for creating a short social-media reel.

Return ONLY valid JSON — no markdown, no explanation. If a field cannot be determined,
use null. Features must be a list of short bullet-point strings (max 8 items, each ≤ 10 words).
Tone options: professional, casual, luxury, energetic, friendly.
"""

_USER_PROMPT = """\
Extract product information from this webpage text:

URL: {url}

PAGE TEXT (first 6000 chars):
{text}

Return exactly this JSON structure:
{{
  "name": "Product name",
  "description": "2-3 sentence product description highlighting benefits",
  "price": "$XX.XX or null",
  "features": ["Feature 1", "Feature 2", "Feature 3"],
  "target_audience": "Who this is for (age, interests, lifestyle)",
  "tone": "one of: professional | casual | luxury | energetic | friendly",
  "confidence": 0.0
}}

confidence = how confident you are in the extraction (0.0–1.0).
Set to 0.0 if the page doesn't appear to be a product/landing page.
"""

_KNOWLEDGE_PROMPT = """\
The product page at this URL could not be fetched directly (the site blocks automated access).
Using your training knowledge, extract product information for this URL:

URL: {url}

Return exactly this JSON structure:
{{
  "name": "Product name",
  "description": "2-3 sentence product description highlighting benefits",
  "price": "approximate price or null",
  "features": ["Feature 1", "Feature 2", "Feature 3"],
  "target_audience": "Who this is for (age, interests, lifestyle)",
  "tone": "one of: professional | casual | luxury | energetic | friendly",
  "confidence": 0.0,
  "from_knowledge": true
}}

confidence = how confident you are based on your training knowledge (0.0–1.0).
If you don't recognise this specific product, set confidence to 0.1.
"""


_BLOCKED_SENTINEL = "__BLOCKED__"


def _fetch_page_text(url: str, timeout: int = 10) -> str:
    """
    Fetch page HTML and return clean readable text.
    Returns _BLOCKED_SENTINEL if the site returns 4xx (bot protection).
    Raises RuntimeError on network/parse failures.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)

        # 4xx = bot protection / login wall → use knowledge fallback
        if resp.status_code in (401, 403, 429) or resp.status_code >= 400:
            return _BLOCKED_SENTINEL

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "noscript", "iframe", "svg"]):
            tag.decompose()

        # Prioritise product-specific containers
        priority_selectors = [
            "[class*='product']", "[class*='item']", "[class*='pdp']",
            "main", "article", "[role='main']",
        ]
        for sel in priority_selectors:
            container = soup.select_one(sel)
            if container:
                text = container.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    return text[:6000]

        # Fallback: full body text
        return soup.get_text(separator=" ", strip=True)[:6000]

    except ImportError:
        raise RuntimeError(
            "httpx and beautifulsoup4 are required for the research agent. "
            "Run: pip install httpx beautifulsoup4"
        )
    except Exception as e:
        # Network error, SSL error, etc. — also try knowledge fallback
        return _BLOCKED_SENTINEL


def _validate_url(url: str) -> str:
    """Basic URL validation — ensure it has a scheme and netloc."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    return url


def run(url: str) -> dict:
    """
    THINK → ACT → OBSERVE: Extract product data from a URL.

    Returns a dict with keys:
        name, description, price, features, target_audience, tone, confidence, source_url
    Raises RuntimeError if extraction fails.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    # ── THINK ─────────────────────────────────────────────────────────────────
    url = _validate_url(url)
    domain = urlparse(url).netloc.replace("www.", "")

    # ── ACT: Fetch ─────────────────────────────────────────────────────────────
    page_text = _fetch_page_text(url)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    from_knowledge = False

    if page_text == _BLOCKED_SENTINEL:
        # Site blocks bots — fall back to Claude's training knowledge about the URL
        from_knowledge = True
        prompt = _KNOWLEDGE_PROMPT.format(url=url)
    elif len(page_text) < 100:
        raise RuntimeError(
            f"Could not extract meaningful text from {url}. "
            "The page may require JavaScript or block bots."
        )
    else:
        prompt = _USER_PROMPT.format(url=url, text=page_text)

    # ── ACT: Extract with Claude ───────────────────────────────────────────────
    response = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude added them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # ── OBSERVE ────────────────────────────────────────────────────────────────
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude returned invalid JSON: {e} — raw: {raw[:200]}")

    confidence = float(data.get("confidence", 0.0))
    if confidence < 0.3:
        raise RuntimeError(
            f"This page doesn't look like a product page (confidence {confidence:.0%}). "
            "Try linking directly to a product listing."
        )

    # Sanitise features list
    features = data.get("features") or []
    if isinstance(features, list):
        features = [str(f)[:80] for f in features if f][:8]

    return {
        "name": data.get("name") or "",
        "description": data.get("description") or "",
        "price": data.get("price"),
        "features": features,
        "target_audience": data.get("target_audience"),
        "tone": data.get("tone") if data.get("tone") in
                ("professional", "casual", "luxury", "energetic", "friendly")
                else "energetic",
        "confidence": confidence,
        "source_url": url,
        "source_domain": domain,
        "from_knowledge": from_knowledge or bool(data.get("from_knowledge")),
    }
