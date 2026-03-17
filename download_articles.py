#!/usr/bin/env python3
"""Download Owen Guo's articles using Playwright + trafilatura + Wayback Machine."""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import trafilatura
from playwright.sync_api import sync_playwright


def slugify(text: str, max_len: int = 80) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:max_len]


def normalize_url(url: str) -> str:
    """Fix old HTTP→HTTPS but don't rewrite paths."""
    url = re.sub(r"^http://", "https://", url)
    return url


def fetch_with_playwright(page, url: str) -> str | None:
    """Fetch page HTML using Playwright headless browser."""
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if resp and resp.status >= 400:
            return None
        page.wait_for_timeout(2000)
        return page.content()
    except Exception as e:
        print(f"    Playwright error: {type(e).__name__}")
        return None


def fetch_wayback(page, url: str) -> str | None:
    """Try fetching from Wayback Machine."""
    wayback_url = f"https://web.archive.org/web/2024/{url}"
    try:
        resp = page.goto(wayback_url, wait_until="domcontentloaded", timeout=25000)
        if resp and resp.status >= 400:
            return None
        page.wait_for_timeout(2000)
        return page.content()
    except Exception as e:
        print(f"    Wayback error: {type(e).__name__}")
        return None


def extract_text(html: str) -> str | None:
    text = trafilatura.extract(
        html,
        output_format="txt",
        include_comments=False,
        include_tables=True,
    )
    return text if text and len(text) >= 100 else None


def main():
    articles_dir = Path(__file__).parent / "articles"
    articles_dir.mkdir(exist_ok=True)

    with open(Path(__file__).parent / "articles.json") as f:
        articles = json.load(f)

    # Deduplicate by normalized URL path
    seen = set()
    unique = []
    for a in articles:
        key = re.sub(r"https?://(www\.)?", "", a["url"]).rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append(a)

    print(f"Downloading {len(unique)} unique articles...\n")

    success = 0
    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        for i, article in enumerate(unique):
            slug = slugify(article["title"])
            out_path = articles_dir / f"{slug}.md"

            if out_path.exists():
                print(f"  [{i+1}/{len(unique)}] SKIP: {article['title'][:60]}")
                success += 1
                continue

            url = normalize_url(article["url"])
            print(f"  [{i+1}/{len(unique)}] {article['title'][:60]}...")

            # Try 1: Direct fetch with Playwright
            html = fetch_with_playwright(page, url)
            text = extract_text(html) if html else None

            # Try 2: trafilatura fetch
            if not text:
                html = trafilatura.fetch_url(url)
                text = extract_text(html) if html else None

            # Try 3: Wayback Machine
            if not text:
                print(f"    Trying Wayback Machine...")
                html = fetch_wayback(page, article["url"])  # use original URL for wayback
                text = extract_text(html) if html else None

            if not text:
                failed.append({"title": article["title"], "url": url})
                print(f"    FAILED")
                continue

            header = f"# {article['title']}\n\n"
            header += f"**Source:** {article['outlet']}  \n"
            header += f"**URL:** {article['url']}  \n"
            header += f"**Date:** {article['date']}  \n\n---\n\n"

            out_path.write_text(header + text, encoding="utf-8")
            success += 1
            print(f"    OK ({len(text)} chars)")

            time.sleep(0.3)

        browser.close()

    print(f"\nDone: {success}/{len(unique)} saved, {len(failed)} failed")
    if failed:
        print("\nFailed:")
        for f in failed:
            print(f"  {f['title'][:60]} — {f['url']}")


if __name__ == "__main__":
    main()
