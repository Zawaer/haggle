"""Browser marketplace adapter: haggle uses mockbay's *website* the way a person would.

Searching, reading listing pages, contacting sellers and chatting all happen in a real Chromium browser
(Playwright): no marketplace API. That makes the adapter shape work for marketplaces without an API.
On our Matrix OS cloud computer it runs headed (HAGGLE_BROWSER_HEADED=1) so you can watch it work;
every step also saves a screenshot that the dashboard shows as "the agent's browser".

Interface (same as market_http.HttpMarket): search(queries) -> listings, send(lid, frm, text, price),
wait_seller(lid, timeout) -> {text, price_sek} | None.

Enable with HAGGLE_MARKET=browser (needs: pip install playwright && playwright install --with-deps chromium).
"""
import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from . import config

BASE = os.environ.get("HAGGLE_MOCKBAY_URL", "https://agentic-hack-mock-marketplace.vercel.app").rstrip("/")
HEADED = os.environ.get("HAGGLE_BROWSER_HEADED") == "1"
SHOTS = config.ROOT / "runs" / "browser"
DETAIL_TABS = 4          # listing pages read in parallel
MAX_LISTINGS = 30

_pw = None
_browser = None
_lock = asyncio.Lock()


def _kr(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


async def _get_browser():
    global _pw, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(headless=not HEADED, args=["--window-size=1280,900"])
    return _browser


# DOM readers (run inside the page)
_READ_CARDS = """() => [...document.querySelectorAll('a.listing-card')].map(a => ({
  id: a.getAttribute('href').split('/').pop(),
  title: a.querySelector('h3')?.textContent.trim() || '',
  price: a.querySelector('.card-bottom strong')?.textContent || '',
}))"""

_READ_LISTING = """() => {
  const q = s => document.querySelector(s);
  const specs = {};
  document.querySelectorAll('.specs > div').forEach(d => {
    const k = d.querySelector('span')?.textContent.trim(), v = d.querySelector('strong')?.textContent.trim();
    if (k && v) specs[k] = v;
  });
  const sellerP = q('.seller p')?.textContent || '';
  return {
    title: q('.detail-info h1')?.textContent.trim() || '',
    price: q('.detail-price')?.textContent || '',
    seller: q('.seller strong')?.childNodes[0]?.textContent.trim() || 'seller',
    sales: (q('.seller strong span')?.textContent || '').replace(/[^0-9]/g, ''),
    rating: (sellerP.match(/★\\s*([0-9.,]+)/) || [])[1] || null,
    since: (sellerP.match(/(19|20)\\d\\d/) || [])[0] || null,
    delivery: q('.purchase-facts.delivery dd')?.innerText || '',
    description: [...document.querySelectorAll('.description p')].map(p => p.innerText).join('\\n'),
    specs,
    photo: q('.large img')?.getAttribute('src') || null,
    available: !q('#contact')?.disabled,
  };
}"""

_READ_THREAD = """() => ({
  seller: [...document.querySelectorAll('#messages .message.seller p')].map(p => p.innerText),
  state: document.querySelector('#thread-state')?.textContent || '',
  total: document.querySelector('.deal-panel .deal-heading b')?.textContent || '',
})"""


class BrowserMarket:
    base = BASE

    def __init__(self, conversation="local"):
        self.conversation = conversation
        self.cursor = {}       # listing id -> seller messages already seen
        self.pages = {}        # listing id -> chat tab
        self.ctx = None
        self.shot_dir = SHOTS / conversation
        self.shot_dir.mkdir(parents=True, exist_ok=True)

    async def _context(self):
        if self.ctx is None:
            browser = await _get_browser()
            self.ctx = await browser.new_context(viewport={"width": 1280, "height": 860}, locale="sv-SE")
            self.ctx.set_default_timeout(20000)
            page = await self.ctx.new_page()
            await page.goto(BASE + "/")
            await page.click("#account")                       # mockbay demo login: just a name
            await page.fill("#login-form input[name=name]", "haggle")
            await page.click("#login-form button.dark")
            await page.wait_for_function("document.querySelector('#account').textContent.trim() === 'haggle'")
            await self._shot(page, "login")
            await page.close()
        return self.ctx

    async def _shot(self, page, label):
        """Latest view of the agent's browser, for the dashboard (best effort)."""
        try:
            data = await page.screenshot(type="jpeg", quality=60)
            tmp = self.shot_dir / f".{id(page)}.jpg"
            tmp.write_bytes(data)
            os.replace(tmp, self.shot_dir / "latest.jpg")  # atomic: tabs screenshot concurrently
            (self.shot_dir / "latest.txt").write_text(f"{time.time():.0f} {label}")
        except Exception:
            pass

    # ------------------------------------------------------------------ search, in the browser
    async def search(self, queries, limit=MAX_LISTINGS):
        ctx = await self._context()
        page = await ctx.new_page()
        ids, cards = [], {}
        try:
            for q in queries:
                words = q.split()
                while words:  # the site's search needs every word: drop words until something matches
                    await page.goto(f"{BASE}/?q={quote(' '.join(words))}")
                    try:
                        await page.wait_for_selector("a.listing-card", timeout=6000)
                    except Exception:
                        words = words[:-1]
                        continue
                    await self._shot(page, f"search: {' '.join(words)}")
                    for c in await page.evaluate(_READ_CARDS):
                        if c["id"] not in cards:
                            cards[c["id"]] = c
                            ids.append(c["id"])
                    break
                if len(ids) >= limit:
                    break
        finally:
            await page.close()
        ids = ids[:limit]
        sem = asyncio.Semaphore(DETAIL_TABS)

        async def read(lid):
            async with sem:
                p = await ctx.new_page()
                try:
                    await p.goto(f"{BASE}/listing/{lid}")
                    await p.wait_for_selector(".detail-info h1")
                    d = await p.evaluate(_READ_LISTING)
                    await self._shot(p, f"reading {d['title'][:40]}")
                    if not d.get("available"):  # sold / reserved: the contact button is disabled
                        return None
                    return self._normalize(lid, d)
                except Exception:
                    return None
                finally:
                    await p.close()

        got = await asyncio.gather(*(read(i) for i in ids))
        return [l for l in got if l]

    def _normalize(self, lid, d):
        specs = "\n".join(f"{k}: {v}" for k, v in d["specs"].items())
        since = int(d["since"]) if d.get("since") else 2020
        photo = d.get("photo")
        if photo and photo.startswith("/"):
            photo = BASE + photo
        return {
            "id": lid, "source": "mockbay (browser)", "title": d["title"] or lid,
            "description": (d["description"] + ("\n\nSpecifikationer:\n" + specs if specs else "")).strip(),
            "price_sek": _kr(d["price"]) or 0, "location": (d["delivery"].split("\n")[-1].split("·")[0]).strip(),
            "shipping": "frakt" in d["delivery"].lower() or "shipping" in d["delivery"].lower(),
            "posted_days_ago": 0,
            "seller": {"name": d["seller"], "account_age_days": max(1, int((2026.75 - since) * 365)),
                       "num_reviews": int(d["sales"] or 0), "rating": float(str(d["rating"]).replace(",", ".")) if d.get("rating") else None},
            "url": f"{BASE}/listing/{lid}", "photo": photo, "photos": [photo] if photo else [],
        }

    # ------------------------------------------------------------------ chat, in the browser
    async def _thread_page(self, lid):
        if lid not in self.pages:
            ctx = await self._context()
            page = await ctx.new_page()
            await page.goto(f"{BASE}/listing/{lid}")
            await page.click("#contact")                      # "Skriv till säljaren" -> opens the chat
            await page.wait_for_url(re.compile(r".*/inbox\?thread="))
            await page.wait_for_selector("#compose input[name=text]")
            self.pages[lid] = page
            self.cursor[lid] = len((await page.evaluate(_READ_THREAD))["seller"])
        return self.pages[lid]

    async def send(self, lid, frm, text, price=None):
        page = await self._thread_page(lid)
        await page.fill("#compose input[name=text]", text[:2000])
        await page.click("#compose button")
        await self._shot(page, f"message to seller of {lid}")
        return {"seq": int(time.time() * 1000), "from": frm, "text": text, "price_sek": price,
                "conversation": self.conversation}

    async def wait_seller(self, lid, timeout=config.HUMAN_REPLY_TIMEOUT):
        page = await self._thread_page(lid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            t = await page.evaluate(_READ_THREAD)
            busy = "funderar" in t["state"] or "considering" in t["state"]
            new = t["seller"][self.cursor.get(lid, 0):]
            if new and not busy:
                await asyncio.sleep(1.0)  # the seller may send two messages in a row
                t = await page.evaluate(_READ_THREAD)
                new = t["seller"][self.cursor.get(lid, 0):]
                self.cursor[lid] = len(t["seller"])
                await self._shot(page, f"seller of {lid} replied")
                # price: read from the seller's words (the deal panel total includes shipping, which mixes
                # item price and delivery); the panel total is added as context for the reader
                text = "\n".join(new) + (f"\n[mockbay deal panel: total {t['total'].strip()} incl. delivery]" if t["total"].strip() else "")
                return {"text": text, "price_sek": None, "thoughts": None}
            await asyncio.sleep(1.0)
        return None

    @property
    def http(self):  # same shutdown hook as HttpMarket (server/restore call market.http.aclose())
        return self

    async def aclose(self):
        await self.close()

    async def close(self):
        if self.ctx:
            await self.ctx.close()
            self.ctx = None
