"""z2u-extend: click "Extend" on every offer in Seller Center -> Active Offers.

Used by z2u_online.py (every EXTEND_MINUTES, default 60) inside the same logged-in
browser, so no extra login or extra GitHub minutes are needed.
Can also be run alone: python z2u_extend.py  (uses Z2U_COOKIES like the other scripts).
"""
import re, sys
from z2u_online import log

MANAGE_URL = "https://www.z2u.com/sell/manage"
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
  // keep the innermost matches only
  const leaf = cands.filter(e => !cands.some(o => o !== e && e.contains(o)));
  leaf.forEach((e, i) => e.setAttribute('data-z2u-ext', String(i)));
  return leaf.length;
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
    try:
        n = page.evaluate(FIND_JS)
    except Exception:
        n = 0
    return [page.locator(f'[data-z2u-ext="{i}"]').first for i in range(n)]


def _confirm(page, before_count):
    """Click a confirm button that appeared in a popup after Extend, if any."""
    page.wait_for_timeout(1500)
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=CONFIRM_RE)
        for i in range(min(loc.count(), 10)):
            el = loc.nth(i)
            try:
                if el.is_visible() and el.bounding_box():
                    txt = (el.inner_text() or "").strip()
                    if EXTEND_RE.match(txt) and len(_extend_buttons(page)) == before_count:
                        continue
                    el.click(timeout=5000)
                    log(f"extend: clicked popup button '{txt}'")
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
    return False


def extend_all(ctx, dry_run=False):
    """Open Active Offers in a new tab and press Extend on each offer. Never raises."""
    page = None
    done = 0
    try:
        page = ctx.new_page()
        page.on("dialog", lambda d: (log(f"extend: site dialog: {d.message[:200]}"), d.accept()))
        page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(4000)
        if any(k in page.url.lower() for k in ("login", "signin")):
            log("extend: not logged in, skipped")
            return 0
        n = len(_extend_buttons(page))
        log(f"extend: found {n} Extend button(s) on Active Offers")
        if n == 0:
            for m in _messages(page):
                log(f"extend: page says: {m}")
            try:
                log(f"extend: page = {page.title()} | {page.url.split('?')[0]}")
                log("extend: clickable texts on page: " + " | ".join(page.evaluate(DIAG_JS)))
            except Exception:
                pass
            return 0
        if dry_run:
            return 0
        for i in range(n):
            if i > 0:
                page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(5000)
            btns = _extend_buttons(page)
            if i >= len(btns):
                break
            try:
                btns[i].scroll_into_view_if_needed(timeout=5000)
                btns[i].click(timeout=8000)
            except Exception as e:
                log(f"extend: offer #{i + 1} click failed: {e.__class__.__name__}")
                continue
            _confirm(page, len(btns))
            page.wait_for_timeout(2000)
            msgs = _messages(page)
            log(f"extend: offer #{i + 1} extended" + (f" | site: {' / '.join(msgs)}" if msgs else ""))
            done += 1
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
