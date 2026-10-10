"""z2u-extend: click "Extend" on every offer in Seller Center -> Active Offers.

Used by z2u_online.py (every EXTEND_MINUTES, default 60) inside the same logged-in
browser, so no extra login or extra GitHub minutes are needed.
Can also be run alone: python z2u_extend.py  (uses Z2U_COOKIES like the other scripts).
"""
import re, sys
from z2u_online import log

MANAGE_URL = "https://www.z2u.com/sell/manage"
LIST_URL = "https://www.z2u.com/sell/manageList"
EXTEND_RE = re.compile(r"^\s*extend\s*$", re.I)
CONFIRM_RE = re.compile(r"^\s*(confirm|ok|yes|sure|submit|extend)\s*$", re.I)

MSG_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = '[class*="layer"],[class*="toast"],[class*="msg"],[class*="alert"],[class*="modal"],[class*="tip"]';
  const out = [];
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e)) continue;
    const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && t.length < 300 && !/ctrl\+d/i.test(t) && !out.includes(t)) out.push(t);
    if (out.length >= 10) break;
  }
  return out;
}
"""


def _messages(page):
    try:
        return page.evaluate(MSG_JS)
    except Exception:
        return []


FIND_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  document.querySelectorAll('[data-z2u-ext]').forEach(e => e.removeAttribute('data-z2u-ext'));
  const re = /extend/i;
  const attr = e => ['title', 'aria-label', 'data-original-title', 'data-title', 'value']
      .map(a => e.getAttribute(a) || '').join(' ');
  const cands = [...document.querySelectorAll('a, button, span, div, i, input, li, [role=button], [onclick]')]
      .filter(e => vis(e) && (
        ((e.innerText || '').trim().length < 30 && re.test(e.innerText || '')) || re.test(attr(e))));
  const leaf = cands.filter(e => !cands.some(o => o !== e && e.contains(o)));
  // keep only buttons that belong to ONE offer (its block shows exactly one offer id like #15095226);
  // the bulk "Extend" in the toolbar belongs to the whole list and is skipped
  const out = [];
  for (const e of leaf) {
    let anc = e.parentElement, id = null;
    for (let k = 0; k < 15 && anc; k++, anc = anc.parentElement) {
      const ids = (anc.innerText || '').match(/#\d{6,}/g);
      if (!ids) continue;
      const uniq = [...new Set(ids)];
      if (uniq.length === 1 && leaf.filter(o => anc.contains(o)).length === 1) id = uniq[0];
      break;
    }
    if (!id) continue;
    e.setAttribute('data-z2u-ext', String(out.length));
    out.push(id);
  }
  return out;
}
"""

DIAG_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  for (const e of document.querySelectorAll('a, button, [role=button], [onclick]')) {
    if (!vis(e)) continue;
    const t = ((e.innerText || '') + ' ' + (e.getAttribute('title') || '')).replace(/\s+/g, ' ').trim();
    if (t && t.length < 40 && !out.includes(t)) out.push(t);
    if (out.length >= 80) break;
  }
  return out;
}
"""


def _extend_buttons(page):
    """Return [(locator, offer_id)] for per-offer Extend buttons."""
    try:
        ids = page.evaluate(FIND_JS)
    except Exception:
        ids = []
    return [(page.locator(f'[data-z2u-ext="{i}"]').first, oid) for i, oid in enumerate(ids)]


def _confirm(page):
    """Click the confirm button of the popup that appears after Extend, if any."""
    page.wait_for_timeout(1500)
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=CONFIRM_RE)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                if el.get_attribute("data-z2u-ext") is not None:
                    continue
                txt = (el.inner_text() or "").strip()
                el.click(timeout=5000)
                log(f"extend: clicked popup button '{txt}'")
                page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
    return False


def _load(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(3000)


def _list_pages(page):
    """Active Offers is split per game/category (sell/manageList?...). Find those links."""
    _load(page, MANAGE_URL)
    try:
        hrefs = page.evaluate("""() => [...new Set([...document.querySelectorAll('a[href*="manageList"]')]
            .map(a => a.href))]""")
    except Exception:
        hrefs = []
    return hrefs or [LIST_URL]


def _extend_on(page, url, dry_run, done_ids):
    _load(page, url)
    first = _extend_buttons(page)
    todo = [oid for _, oid in first if oid not in done_ids]
    log(f"extend: {len(first)} offer(s) on {url.split('//')[-1][:80]}, {len(todo)} not done yet")
    if not first:
        try:
            log("extend: clickable texts on page: " + " | ".join(page.evaluate(DIAG_JS)[:60]))
        except Exception:
            pass
    if dry_run:
        return 0
    done = 0
    for oid in todo:
        if done:
            _load(page, url)
        btn = next((b for b, o in _extend_buttons(page) if o == oid), None)
        if btn is None:
            log(f"extend: offer {oid} not found any more")
            continue
        try:
            btn.scroll_into_view_if_needed(timeout=5000)
            btn.click(timeout=8000)
        except Exception as e:
            log(f"extend: offer {oid} click failed: {e.__class__.__name__}")
            continue
        _confirm(page)
        page.wait_for_timeout(2000)
        msgs = [m for m in _messages(page) if m != "0" and "insufficient stock" not in m.lower()]
        log(f"extend: offer {oid} extended" + (f" | site: {' / '.join(msgs)}" if msgs else ""))
        done_ids.add(oid)
        done += 1
    return done


def extend_all(ctx, dry_run=False):
    """Press EXTEND on every offer in Active Offers (all categories). Never raises."""
    page = None
    done = 0
    try:
        page = ctx.new_page()
        page.on("dialog", lambda d: (log(f"extend: site dialog: {d.message[:200]}"), d.accept()))
        urls = _list_pages(page)
        if any(k in page.url.lower() for k in ("login", "signin")):
            log("extend: not logged in, skipped")
            return 0
        log(f"extend: {len(urls)} offer list page(s) to check")
        done_ids = set()
        # check unfiltered lists first, then filtered ones (e.g. listing=low_stock)
        urls = sorted(urls[:10], key=lambda u: "listing=" in u)
        for url in urls:
            done += _extend_on(page, url, dry_run, done_ids)
    except Exception as e:
        log(f"extend: problem {e.__class__.__name__}: {str(e)[:150]}")
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
    return done


if __name__ == "__main__":
    import os
    from playwright.sync_api import sync_playwright
    from z2u_online import load_cookies, UA
    dry = (os.environ.get("MODE") or "").lower() == "dry-run"
    cookies = load_cookies()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        c = b.new_context(user_agent=UA, viewport={"width": 1366, "height": 900}, locale="en-US")
        c.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        c.add_cookies(cookies)
        extend_all(c, dry_run=dry)
        b.close()
