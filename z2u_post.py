"""z2u-post: create a Clash of Clans account listing on z2u from a JSON file.

MODE=dry-run (default): fills the whole form and takes screenshots, does NOT submit.
MODE=publish: same, then ticks the terms box and clicks Submit.
Listing data lives in listings/<name>.json (see listings/example.json).
Images must be direct links on a host z2u accepts (imgur, postimages, dropbox, flickr...).
Never prints cookie values.
"""
import json, os, sys
from playwright.sync_api import sync_playwright
from z2u_online import load_cookies, state, log, UA
from z2u_inspect import pick_game_and_category

LISTING = (os.environ.get("LISTING") or "listings/example.json").strip()
MODE = (os.environ.get("MODE") or "dry-run").strip().lower()
REPO = os.environ.get("GITHUB_REPOSITORY", "")
REF = os.environ.get("GITHUB_REF_NAME", "main")
OUT = "post"
SELL_URL = "https://www.z2u.com/sell/create"

TEXT_FIELDS = [
    ("Title", "title", "input"),
    ("Discription", "description", "textarea"),
    ("Price Per Unit", "price", "input"),
    ("Min Unit Per Order", "min_unit", "input"),
    ("Stock", "stock", "input"),
    ("Barbarian King Amount", "bk_amount", "input"),
    ("Archer Queen Amount", "aq_amount", "input"),
    ("Grand Warden Amount", "gw_amount", "input"),
    ("Royal Champion Amount", "rc_amount", "input"),
    ("Hero Skins Amount", "hero_skins", "input"),
    ("Gems", "gems", "input"),
    ("War Stars", "war_stars", "input"),
    ("Clan War Leagues Medals", "cwl_medals", "input"),
    ("Experience Level", "experience_level", "input"),
]
SELECT_FIELDS = [
    ("Accounts Type", "town_hall"),
    ("Currency", "currency"),
    ("Require Integer", "require_integer"),
    ("Barbarian King level", "bk_level"),
    ("Archer Queen level", "aq_level"),
    ("Grand Warden level", "gw_level"),
    ("Royal Champion level", "rc_level"),
]

HELPERS_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').replace(/[*:]/g, '').trim().toLowerCase();
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ownText = e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
  const skip = ['SCRIPT', 'STYLE', 'OPTION', 'SELECT', 'TEXTAREA', 'BUTTON', 'INPUT'];
  const labels = want => [...document.querySelectorAll('body *')].filter(e =>
      !skip.includes(e.tagName) && vis(e) && norm(ownText(e)) === want);
  const sectionOf = title => {
    for (const lab of labels(norm(title))) {
      let anc = lab;
      for (let k = 0; k < 8 && anc; k++, anc = anc.parentElement) {
        if (anc.querySelectorAll('select, input, button').length >= 2) return anc;
      }
    }
    return null;
  };
  window.__z2u = {
    mark(label, kinds, key) {
      for (const lab of labels(norm(label))) {
        let anc = lab;
        for (let k = 0; k < 5 && anc; k++, anc = anc.parentElement) {
          const ctl = [...anc.querySelectorAll(kinds)].find(c =>
              lab.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING);
          if (ctl) { ctl.setAttribute('data-z2u', key); return true; }
        }
      }
      return false;
    },
    markInSection(title, text, key) {
      const sec = sectionOf(title);
      if (!sec) return false;
      const t = norm(text);
      const hit = [...sec.querySelectorAll('*')].find(e =>
          vis(e) && e.children.length <= 1 && norm(e.innerText) === t);
      if (!hit) return false;
      hit.setAttribute('data-z2u', key);
      return true;
    },
    markTerms(key) {
      for (const c of document.querySelectorAll('input[type=checkbox]')) {
        let anc = c.parentElement;
        for (let k = 0; k < 3 && anc; k++, anc = anc.parentElement) {
          if (/have read and agreed/i.test(anc.innerText || '')) { c.setAttribute('data-z2u', key); return true; }
        }
      }
      return false;
    },
    select(key, wanted) {
      const el = document.querySelector('[data-z2u="' + key + '"]');
      if (!el || !el.options) return { ok: false, options: [] };
      const opts = [...el.options];
      const w = norm(wanted);
      const o = opts.find(x => norm(x.text) === w) || opts.find(x => norm(x.text).includes(w));
      const list = opts.map(x => x.text.trim());
      if (!o) return { ok: false, options: list };
      el.value = o.value;
      o.selected = true;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      if (window.jQuery) {
        try {
          const $e = window.jQuery(el);
          if ($e.selectpicker) $e.selectpicker('refresh');
          $e.trigger('change');
        } catch (e) {}
      }
      return { ok: true, chosen: o.text.trim(), options: list };
    },
    setValue(key, v) {
      const el = document.querySelector('[data-z2u="' + key + '"]');
      if (!el) return false;
      el.removeAttribute('readonly');
      el.value = v;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    },
    sectionSelects(title) {
      const sec = sectionOf(title);
      if (!sec) return [];
      return [...sec.querySelectorAll('select')].map(s => {
        let row = s.parentElement, lab = '';
        for (let k = 0; k < 4 && row && !lab; k++, row = row.parentElement) {
          const t = (row.innerText || '').split('\n').map(x => x.trim()).filter(Boolean);
          if (t.length && t[0].length < 40 && !/please select/i.test(t[0])) lab = t[0];
        }
        return { label: lab, options: [...s.options].map(o => o.text.trim()).slice(0, 40) };
      });
    },
    menuItems(key) {
      const b = document.querySelector('[data-z2u="' + key + '"]');
      if (!b) return [];
      document.querySelectorAll('[data-z2u-opt]').forEach(e => e.removeAttribute('data-z2u-opt'));
      let anc = b.parentElement;
      for (let k = 0; k < 4 && anc; k++, anc = anc.parentElement) {
        const items = [...anc.querySelectorAll('li, .dropdown-item, [role=option]')].filter(e =>
            vis(e) && !e.contains(b) && !b.contains(e) && e.children.length <= 3 &&
            (e.innerText || '').trim() && (e.innerText || '').trim().length < 60);
        if (items.length) {
          return items.map((e, i) => { e.setAttribute('data-z2u-opt', String(i)); return (e.innerText || '').replace(/\s+/g, ' ').trim(); });
        }
      }
      return [];
    },
    messages() {
      const sel = '[class*="layer"],[class*="toast"],[class*="msg"],[class*="alert"],[class*="error"],.help-block,.invalid-feedback';
      const out = [];
      for (const e of document.querySelectorAll(sel)) {
        if (!vis(e)) continue;
        const t = (e.innerText || '').replace(/\s+/g, ' ').trim();
        if (t && t.length < 300 && !out.includes(t)) out.push(t);
        if (out.length >= 20) break;
      }
      return out;
    },
  };
  return true;
}
"""


def js(page, expr, arg=None):
    return page.evaluate(expr, arg)


def install(page):
    js(page, HELPERS_JS)


def mark(page, label, kinds, key):
    return js(page, "([l, k, y]) => window.__z2u.mark(l, k, y)", [label, kinds, key])


def show_messages(page, title):
    try:
        msgs = js(page, "() => window.__z2u.messages()")
    except Exception:
        msgs = []
    if msgs:
        log(f"{title}: site messages:")
        for m in msgs:
            print("    " + m, flush=True)


DROPDOWN_KINDS = 'button, [role=button], .dropdown-toggle, [class*="select"]'


def norm(s):
    return " ".join(str(s).replace("*", "").replace(":", "").split()).lower()


def set_dropdown(page, label, value, key):
    if not mark(page, label, DROPDOWN_KINDS, key):
        log(f"MISSING select: {label}")
        return
    try:
        page.locator(f'[data-z2u="{key}"]').first.click(timeout=8000)
    except Exception as e:
        log(f"could not open dropdown {label}: {e.__class__.__name__}")
        return
    page.wait_for_timeout(1500)
    items = js(page, "(k) => window.__z2u.menuItems(k)", key)
    log(f"dropdown {label} options: {' | '.join(items) if items else '(none found)'}")
    w = norm(value)
    idx = next((i for i, t in enumerate(items) if norm(t) == w), None)
    if idx is None:
        idx = next((i for i, t in enumerate(items) if w in norm(t)), None)
    if idx is None:
        log(f"VALUE NOT FOUND for {label}: {value!r}")
        page.keyboard.press("Escape")
        return
    page.locator(f'[data-z2u-opt="{idx}"]').first.click(timeout=8000)
    log(f"set {label} = {items[idx]}")
    page.wait_for_timeout(1000)


def set_select(page, label, value, key):
    if value in (None, ""):
        return
    if not mark(page, label, "select", key):
        set_dropdown(page, label, value, key)
        return
    r = js(page, "([k, v]) => window.__z2u.select(k, v)", [key, str(value)])
    if r.get("ok"):
        log(f"set {label} = {r['chosen']}")
    else:
        log(f"VALUE NOT FOUND for {label}: {value!r}. options: {' | '.join(r.get('options', []))}")
    page.wait_for_timeout(700)


def set_text(page, label, value, key, kinds):
    if value in (None, ""):
        return
    if not mark(page, label, kinds, key):
        log(f"MISSING field: {label}")
        return
    loc = page.locator(f'[data-z2u="{key}"]')
    try:
        loc.fill(str(value), timeout=8000)
    except Exception:
        js(page, "([k, v]) => window.__z2u.setValue(k, v)", [key, str(value)])
    log(f"set {label}")


def click_marked(page, key, what):
    try:
        page.locator(f'[data-z2u="{key}"]').first.click(timeout=8000)
        log(f"clicked {what}")
        page.wait_for_timeout(800)
        return True
    except Exception as e:
        log(f"could not click {what}: {e.__class__.__name__}")
        return False


IMAGE_HOSTS = ("imgur.com", "dropbox.com", "dropboxusercontent.com", "flickr.com",
               "staticflickr.com", "500px.com", "500px.org", "postimages.org",
               "postimg.cc", "hizliresim.com")


def image_url(path):
    url = path if path.startswith(("http://", "https://")) else \
        f"https://raw.githubusercontent.com/{REPO}/{REF}/{path.lstrip('/')}"
    if not any(h in url.lower() for h in IMAGE_HOSTS):
        log(f"WARNING: z2u may reject this image host: {url}")
    return url


def fill_form(ctx, page, d):
    # Product Types
    try:
        page.locator("#attr-0").check(force=True, timeout=8000)
        log("checked Attribute: Account Ownership Transfer")
    except Exception as e:
        log(f"could not check Attribute radio: {e.__class__.__name__}")
    page.wait_for_timeout(2500)
    install(page)
    for i, (label, value) in enumerate((d.get("product_types") or {}).items()):
        set_select(page, label, value, f"pt{i}")
        page.wait_for_timeout(1500)
        install(page)

    # Game details
    for label, key, kinds in TEXT_FIELDS:
        set_text(page, label, d.get(key), key, kinds)
    for label, key in SELECT_FIELDS:
        set_select(page, label, d.get(key), key)
    if d.get("registration_time"):
        if mark(page, "Registration time", "input", "regtime"):
            js(page, "([k, v]) => window.__z2u.setValue(k, v)", ["regtime", str(d["registration_time"])])
            page.keyboard.press("Escape")
            log("set Registration time")
        else:
            log("MISSING field: Registration time")

    # Images
    url_box = page.get_by_placeholder("Enter image URL").first
    add_btn = page.get_by_role("button", name="Add Image").first
    for path in d.get("images") or []:
        url = image_url(path)
        try:
            url_box.fill(url, timeout=8000)
            add_btn.click(timeout=8000)
            page.wait_for_timeout(3500)
            log(f"added image: {path}")
            show_messages(page, "after image")
        except Exception as e:
            log(f"could not add image {path}: {e.__class__.__name__}")

    # Expiration, delivery, publish time
    if d.get("expiration") and js(page, "([t, v, k]) => window.__z2u.markInSection(t, v, k)",
                                  ["Product Expiration Date", d["expiration"], "exp"]):
        click_marked(page, "exp", f"expiration {d['expiration']}")
    set_select(page, "DELIVERY ETA", d.get("delivery_eta"), "eta")
    pub = d.get("publish") or "Publish Immediately"
    if js(page, "([t, v, k]) => window.__z2u.markInSection(t, v, k)", ["Publish Time", pub, "pub"]):
        click_marked(page, "pub", pub)


def main():
    if MODE not in ("dry-run", "publish"):
        sys.exit("MODE must be dry-run or publish")
    try:
        with open(LISTING, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        sys.exit(f"cannot read listing file {LISTING}: {e}")
    log(f"listing: {LISTING} | mode: {MODE}")
    cookies = load_cookies()
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900},
                                  locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        def on_dialog(dlg):
            log(f"site dialog: {dlg.message[:300]}")
            dlg.accept()

        page.on("dialog", on_dialog)
        page.goto(SELL_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        st = state(page)
        log(f"status: {st}")
        if st in ("out", "blocked"):
            page.screenshot(path=f"{OUT}/error.png", full_page=True)
            browser.close()
            sys.exit(f"status = {st}, cannot create the listing.")

        page = pick_game_and_category(ctx, page)
        page.on("dialog", on_dialog)
        install(page)
        if not mark(page, "Title", "input", "probe"):
            page.screenshot(path=f"{OUT}/error.png", full_page=True)
            browser.close()
            sys.exit("Listing form did not open (no Title field). See post/error.png.")

        fill_form(ctx, page, d)
        page.wait_for_timeout(1500)
        show_messages(page, "after filling")
        page.screenshot(path=f"{OUT}/filled.png", full_page=True)
        log("screenshot saved: post/filled.png")

        if MODE == "publish":
            install(page)
            if js(page, "(k) => window.__z2u.markTerms(k)", "terms"):
                try:
                    page.locator('[data-z2u="terms"]').check(force=True, timeout=8000)
                    log("ticked terms checkbox")
                except Exception as e:
                    log(f"could not tick terms: {e.__class__.__name__}")
            else:
                log("terms checkbox not found")
            before = page.url
            page.get_by_role("button", name="Submit").last.click(timeout=10000)
            log("clicked Submit")
            page.wait_for_timeout(10000)
            install(page)
            show_messages(page, "after submit")
            page.screenshot(path=f"{OUT}/after_submit.png", full_page=True)
            log(f"page after submit: {page.url}")
            if page.url == before:
                log("NOTE: still on the form page, check post/after_submit.png and the messages above")
        else:
            log("DRY RUN: nothing was submitted.")
        browser.close()


if __name__ == "__main__":
    main()
