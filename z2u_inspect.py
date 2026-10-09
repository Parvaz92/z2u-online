"""z2u-inspect: one-off scan of the z2u 'sell / add offer' form.

Opens the sell form with your Z2U_COOKIES, lists every form field (type, name,
label, dropdown options) and buttons, and saves a screenshot. This is step 1 of
auto-listing: the real listing script is written from this output.
It NEVER clicks submit, never prints cookie values and never reads input values.
"""
import json, os, sys
from playwright.sync_api import sync_playwright
from z2u_online import load_cookies, state, log, UA

START_URL = "https://www.z2u.com/"
TARGET_URL = (os.environ.get("TARGET_URL") or "").strip()
OUT_DIR = "inspect"

SCAN_JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const labelOf = e => {
    let t = '';
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) t = l.innerText; }
    if (!t) { const l = e.closest('label'); if (l) t = l.innerText; }
    if (!t) {
      let p = e.parentElement;
      for (let k = 0; k < 3 && p && !t; k++) {
        const s = (p.innerText || '').trim();
        if (s && s.length < 120) t = s;
        p = p.parentElement;
      }
    }
    return (t || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  };
  const fields = [];
  document.querySelectorAll('input, select, textarea, [contenteditable="true"]').forEach((e, i) => {
    const type = (e.getAttribute('type') || '').toLowerCase();
    if (type === 'hidden') return;
    fields.push({
      i, tag: e.tagName.toLowerCase(), type,
      name: e.getAttribute('name') || '', id: e.id || '',
      placeholder: e.getAttribute('placeholder') || '',
      aria: e.getAttribute('aria-label') || '',
      label: labelOf(e), visible: vis(e), required: !!e.required,
      options: e.tagName === 'SELECT'
        ? [...e.options].slice(0, 60).map(o => o.text.trim() + ' = ' + o.value) : undefined
    });
  });
  const buttons = [...document.querySelectorAll('button, [role=button], input[type=submit]')]
    .filter(vis).map(b => (b.innerText || b.value || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean).slice(0, 80);
  const links = [...document.querySelectorAll('a[href]')]
    .filter(a => /sell|offer|publish|post/i.test(a.getAttribute('href') + ' ' + a.innerText))
    .map(a => ({ text: a.innerText.replace(/\s+/g, ' ').trim().slice(0, 60), href: a.href.split('?')[0] }))
    .slice(0, 60);
  return { fields, buttons, links };
}
"""


def main():
    cookies = load_cookies()
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(TARGET_URL or START_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        st = state(page)
        log(f"status: {st}")
        if st in ("out", "blocked"):
            page.screenshot(path=f"{OUT_DIR}/page.png", full_page=True)
            browser.close()
            sys.exit(f"status = {st}, cannot inspect the sell form.")

        if not TARGET_URL:
            sell = page.locator(r'a:text-matches("^\s*sell", "i")').first
            if sell.count() > 0:
                log("no TARGET_URL given, clicking the site's 'Sell' link")
                try:
                    sell.click(timeout=15000)
                    page.wait_for_load_state("domcontentloaded", timeout=60000)
                    page.wait_for_timeout(6000)
                except Exception as e:
                    log(f"could not open Sell link: {e.__class__.__name__}")
            else:
                log("no 'Sell' link found on the home page")

        data = page.evaluate(SCAN_JS)
        data["url"] = page.url.split("?")[0]
        data["title"] = page.title()
        with open(f"{OUT_DIR}/form.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        page.screenshot(path=f"{OUT_DIR}/page.png", full_page=True)
        browser.close()

    print("=" * 60, flush=True)
    print(f"PAGE: {data['title']} | {data['url']}")
    print(f"FIELDS ({len(data['fields'])}):")
    for fl in data["fields"]:
        if not fl["visible"]:
            continue
        line = (f"  #{fl['i']} {fl['tag']}[{fl['type']}] name={fl['name']!r} id={fl['id']!r} "
                f"label={fl['label']!r} placeholder={fl['placeholder']!r}"
                f"{' REQUIRED' if fl['required'] else ''}")
        print(line)
        if fl.get("options"):
            print("      options: " + " | ".join(fl["options"][:25]))
    print("BUTTONS: " + " | ".join(data["buttons"]))
    print("SELL/OFFER LINKS:")
    for ln in data["links"][:30]:
        print(f"  {ln['text']!r} -> {ln['href']}")
    print("=" * 60, flush=True)
    log("inspect done. Nothing was submitted.")


if __name__ == "__main__":
    main()
