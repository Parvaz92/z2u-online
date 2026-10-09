"""z2u-inspect: one-off scan of the z2u 'sell / add offer' form.

Opens the sell form with your Z2U_COOKIES. On /sell/create it types the game
name and clicks the category label (default: Accounts) inside the game's
suggestion row (default: Clash Of Clans (Global)), then lists every form field
(type, name, label, dropdown options) and buttons, and saves a screenshot.
It NEVER clicks submit, never prints cookie values and never reads input values.
"""
import json, os, re, sys
from playwright.sync_api import sync_playwright
from z2u_online import load_cookies, state, log, UA

START_URL = "https://www.z2u.com/"
TARGET_URL = (os.environ.get("TARGET_URL") or "").strip()
GAME_SEARCH = os.environ.get("GAME_SEARCH") or "Clash of Clans"
GAME_PICK = os.environ.get("GAME_PICK") or "Clash Of Clans (Global)"
CATEGORY = os.environ.get("CATEGORY") or "Accounts"
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
  return { fields, buttons };
}
"""


def game_row(page):
    title = re.compile(r"^\s*" + re.escape(GAME_PICK) + r"\s*$", re.I)
    return page.locator("li.labelListLi").filter(
        has=page.locator("div.bigTitle", has_text=title)).first


def pick_game_and_category(ctx, page):
    kw = page.locator("#keywords")
    if kw.count() == 0:
        log("no search box on this page, skipping game/category pick")
        return page
    box = kw.first
    box.click()
    box.fill("")
    box.type(GAME_SEARCH, delay=80)
    page.wait_for_timeout(4000)

    row = game_row(page)
    if row.count() == 0:
        log(f"suggestion row for '{GAME_PICK}' not found")
        return page
    try:
        html = row.evaluate("e => e.outerHTML")
        print("--- game row HTML (first 2500 chars) ---", flush=True)
        print(re.sub(r"\s+", " ", html)[:2500], flush=True)
    except Exception:
        pass

    cat = row.get_by_text(CATEGORY, exact=True)
    if cat.count() == 0:
        log(f"category '{CATEGORY}' not found inside the '{GAME_PICK}' row")
        return page
    pages_before = len(ctx.pages)
    cat.first.click(timeout=10000)
    log(f"clicked: {GAME_PICK} -> {CATEGORY}")
    page.wait_for_timeout(3000)
    if len(ctx.pages) > pages_before:
        page = ctx.pages[-1]
        log("category opened in a new tab, switched to it")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception:
        pass
    page.wait_for_timeout(6000)
    return page


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
        page.goto(TARGET_URL or "https://www.z2u.com/sell/create",
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        st = state(page)
        log(f"status: {st}")
        if st in ("out", "blocked"):
            page.screenshot(path=f"{OUT_DIR}/page.png", full_page=True)
            browser.close()
            sys.exit(f"status = {st}, cannot inspect the sell form.")

        if "/sell/create" in page.url.lower():
            try:
                page = pick_game_and_category(ctx, page)
            except Exception as e:
                log(f"game/category pick problem: {e.__class__.__name__}: {str(e)[:200]}")

        data = page.evaluate(SCAN_JS)
        data["url"] = page.url
        data["title"] = page.title()
        with open(f"{OUT_DIR}/form.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        page.screenshot(path=f"{OUT_DIR}/page.png", full_page=True)
        browser.close()

    print("=" * 60, flush=True)
    print(f"PAGE: {data['title']} | {data['url']}")
    print(f"FIELDS ({len(data['fields'])}):")
    for fl in data["fields"]:
        if not fl["visible"] and not fl["name"]:
            continue
        line = (f"  #{fl['i']} {fl['tag']}[{fl['type']}] name={fl['name']!r} id={fl['id']!r} "
                f"label={fl['label']!r} placeholder={fl['placeholder']!r}"
                f"{' REQUIRED' if fl['required'] else ''}{'' if fl['visible'] else ' (not visible)'}")
        print(line)
        if fl.get("options"):
            print("      options: " + " | ".join(fl["options"][:25]))
    print("BUTTONS: " + " | ".join(data["buttons"]))
    print("=" * 60, flush=True)
    log("inspect done. Nothing was submitted.")


if __name__ == "__main__":
    main()
