"""z2u-post: create a Clash of Clans account listing on z2u from a JSON file.

MODE=dry-run (default): fills the whole form and takes screenshots, does NOT submit.
MODE=publish: same, then ticks the terms box and clicks Submit.
Listing data lives in listings/<name>.json (see listings/example.json).
Dropdown values may be a list of candidates; the first one the site offers is used.
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
    markVis(label, kinds, key) {
      for (const lab of labels(norm(label))) {
        let anc = lab;
        for (let k = 0; k < 5 && anc; k++, anc = anc.parentElement) {
          const ctl = [...anc.querySelectorAll(kinds)].find(c => vis(c) &&
              (lab.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING));
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
    snapshot() {
      window.__z2uSeen = new Set([...document.querySelectorAll('body *')].filter(vis));
      return true;
    },
    newItems() {
      const seen = window.__z2uSeen || new Set();
      document.querySelectorAll('[data-z2u-opt]').forEach(e => e.removeAttribute('data-z2u-opt'));
      const items = [...document.querySelectorAll('body *')].filter(e => {
        if (seen.has(e) || !vis(e) || e.children.length > 2) return false;
        const t = (e.innerText || '').trim();
        return t && t.length < 60 && !/please select/i.test(t);
      });
      return items.map((e, i) => { e.setAttribute('data-z2u-opt', String(i)); return (e.innerText || '').replace(/\s+/g, ' ').trim(); });
    },
    rowHtml(key) {
      const b = document.querySelector('[data-z2u="' + key + '"]');
      if (!b) return '';
      let anc = b;
      for (let k = 0; k < 3 && anc.parentElement; k++) anc = anc.parentElement;
      return anc.outerHTML.replace(/\s+/g, ' ').slice(0, 3000);
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


DROPDOWN_KINDS = '.dropdown-toggle, button, [role=button], [role=combobox]'


def norm(s):
    return " ".join(str(s).replace("*", "").replace(":", "").split()).lower()


def _open_menu(page, label, key):
    try:
        page.keyboard.press("Escape")
        js(page, "() => document.body.click()")
    except Exception:
        pass
    page.wait_for_timeout(1200)
    install(page)
    if not js(page, "([l, k, y]) => window.__z2u.markVis(l, k, y)", [label, DROPDOWN_KINDS, key]):
        return None
    js(page, "() => window.__z2u.snapshot()")
    loc = page.locator(f'[data-z2u="{key}"]').first
    try:
        loc.scroll_into_view_if_needed(timeout=5000)
        loc.click(timeout=8000)
    except Exception:
        try:
            loc.click(timeout=8000, force=True)
        except Exception as e:
            log(f"could not open dropdown {label}: {e.__class__.__name__}")
            return None
    page.wait_for_timeout(1800)
    items = js(page, "(k) => window.__z2u.menuItems(k)", key)
    if not items:
        items = js(page, "() => window.__z2u.newItems()")
    return items


def _shown(page, key):
    try:
        return norm(page.locator(f'[data-z2u="{key}"]').first.inner_text(timeout=3000))
    except Exception:
        return ""


def set_dropdown(page, label, value, key):
    items = _open_menu(page, label, key)
    if items is None:
        log(f"MISSING dropdown: {label}")
        return False
    log(f"dropdown {label} options: {' | '.join(items) if items else '(none found)'}")
    if not items:
        print(f"--- {label} row HTML ---", flush=True)
        print(js(page, "(k) => window.__z2u.rowHtml(k)", key), flush=True)
        return False
    want = None
    for cand in (value if isinstance(value, list) else [value]):
        w = norm(cand)
        if any(norm(t) == w for t in items):
            want = w
            break
    if want is None:
        log(f"VALUE NOT FOUND for {label}: {value!r}")
        page.keyboard.press("Escape")
        return False
    hits = [i for i, t in enumerate(items) if norm(t) == want]
    # try the deepest element first (it usually carries the click handler)
    for n, _ in enumerate(reversed(hits)):
        if n > 0:
            items = _open_menu(page, label, key) or []
            hits2 = [i for i, t in enumerate(items) if norm(t) == want]
            if len(hits2) <= n:
                break
            idx = list(reversed(hits2))[n]
        else:
            idx = list(reversed(hits))[0]
        try:
            page.locator(f'[data-z2u-opt="{idx}"]').first.click(timeout=8000)
        except Exception:
            try:
                page.locator(f'[data-z2u-opt="{idx}"]').first.click(timeout=8000, force=True)
            except Exception as e:
                log(f"click on option failed: {e.__class__.__name__}")
                continue
        page.wait_for_timeout(1200)
        shown = _shown(page, key)
        if want in shown and "please select" not in shown:
            log(f"set {label} = {want} (verified)")
            return True
        log(f"{label}: option click #{n + 1} did not stick (shows {shown!r})")
    # keyboard fallback
    items = _open_menu(page, label, key)
    if items is not None:
        try:
            page.keyboard.type(want, delay=60)
            page.wait_for_timeout(800)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1200)
        except Exception:
            pass
        shown = _shown(page, key)
        if want in shown and "please select" not in shown:
            log(f"set {label} = {want} (verified, keyboard)")
            return True
    # hidden <select> in the same row
    ok = js(page, """([k, w]) => {
        const b = document.querySelector('[data-z2u="' + k + '"]');
        if (!b) return false;
        let anc = b;
        for (let i = 0; i < 4 && anc.parentElement; i++) {
            anc = anc.parentElement;
            const s = anc.querySelector('select');
            if (!s) continue;
            const o = [...s.options].find(x => (x.text || '').trim().toLowerCase() === w);
            if (!o) return false;
            s.value = o.value; o.selected = true;
            s.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) { try { const $s = window.jQuery(s); if ($s.selectpicker) $s.selectpicker('refresh'); $s.trigger('change'); } catch (e) {} }
            return true;
        }
        return false;
    }""", [key, want])
    page.wait_for_timeout(1200)
    shown = _shown(page, key)
    if want in shown and "please select" not in shown:
        log(f"set {label} = {want} (verified, hidden select)")
        return True
    log(f"FAILED to set {label} (hidden select found: {ok}, shows {shown!r})")
    print(f"--- {label} row HTML ---", flush=True)
    print(js(page, "(k) => window.__z2u.rowHtml(k)", key), flush=True)
    return False


def set_select(page, label, value, key):
    if value in (None, ""):
        return
    if not mark(page, label, "select", key):
        set_dropdown(page, label, value, key)
        return
    r = {}
    for cand in (value if isinstance(value, list) else [value]):
        r = js(page, "([k, v]) => window.__z2u.select(k, v)", [key, str(cand)])
        if r.get("ok"):
            break
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


def tick_terms(page, submit):
    """Tick 'I have read and agreed...' and wait until Submit is enabled."""
    def ready():
        try:
            return submit.is_enabled()
        except Exception:
            return False

    if not js(page, "(k) => window.__z2u.markTerms(k)", "terms"):
        log("terms checkbox not found")
    box = page.locator('[data-z2u="terms"]').first
    attempts = [
        ("text click", lambda: page.get_by_text("I have read and agreed", exact=False).first.click(timeout=5000)),
        ("checkbox click", lambda: box.click(timeout=5000)),
        ("checkbox force click", lambda: box.click(timeout=5000, force=True)),
        ("js", lambda: js(page, """() => {
            const c = document.querySelector('[data-z2u="terms"]');
            if (!c) return false;
            c.checked = true;
            c.dispatchEvent(new Event('click', { bubbles: true }));
            c.dispatchEvent(new Event('change', { bubbles: true }));
            if (window.jQuery) { try { window.jQuery(c).prop('checked', true).trigger('change'); } catch (e) {} }
            return true;
        }""")),
    ]
    def checked():
        try:
            return bool(js(page, "() => { const c = document.querySelector('[data-z2u=\"terms\"]'); return !!(c && c.checked); }"))
        except Exception:
            return False

    for name, act in attempts:
        if ready():
            break
        if name != "js" and checked():
            log(f"terms already checked, skipping {name}")
            continue
        try:
            act()
        except Exception as e:
            log(f"terms {name} failed: {e.__class__.__name__}")
        page.wait_for_timeout(1500)
        log(f"after terms {name}: submit enabled = {ready()}")
    if ready():
        log("terms ticked, Submit is enabled")
        return True
    return False


def fill_form(ctx, page, d):
    # Product Types
    try:
        page.locator("#attr-0").check(force=True, timeout=8000)
        log("checked Attribute: Account Ownership Transfer")
    except Exception as e:
        log(f"could not check Attribute radio: {e.__class__.__name__}")
    page.wait_for_timeout(2500)
    install(page)
    failed = []
    for i, (label, value) in enumerate((d.get("product_types") or {}).items()):
        if not set_dropdown(page, label, value, f"pt{i}"):
            failed.append(label)
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
    return failed


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

        failed = fill_form(ctx, page, d)
        page.wait_for_timeout(1500)
        show_messages(page, "after filling")
        page.screenshot(path=f"{OUT}/filled.png", full_page=True)
        log("screenshot saved: post/filled.png")

        if failed:
            log(f"REQUIRED DROPDOWNS NOT SET: {', '.join(failed)}")
        if MODE == "publish" and failed:
            browser.close()
            sys.exit("Not submitting because these required fields are empty: " + ", ".join(failed))
        if MODE == "publish":
            install(page)
            submit = page.locator("button.submitSell").last
            if not tick_terms(page, submit):
                page.screenshot(path=f"{OUT}/after_submit.png", full_page=True)
                show_messages(page, "terms")
                browser.close()
                sys.exit("Submit button stayed disabled: terms checkbox could not be ticked. See post/after_submit.png.")
            before = page.url
            posts = []
            page.on("response", lambda r: posts.append(r) if r.request.method == "POST" else None)
            submit.click(timeout=10000)
            log("clicked Submit")
            seen = []
            for sec in range(12):
                page.wait_for_timeout(1000)
                if sec == 1:
                    page.screenshot(path=f"{OUT}/after_submit_2s.png", full_page=False)
                try:
                    install(page)
                    for m in js(page, "() => window.__z2u.messages()"):
                        if m not in seen and "Ctrl+D" not in m:
                            seen.append(m)
                            log(f"site message after submit: {m}")
                except Exception:
                    pass
            for r in posts:
                try:
                    body = " ".join(r.text().split())[:800]
                except Exception as e:
                    body = f"(no body: {e.__class__.__name__})"
                log(f"POST {r.url.split('?')[0]} -> {r.status}: {body}")
            if not posts:
                log("no POST request was sent after Submit (form was blocked by the page itself)")
            page.screenshot(path=f"{OUT}/after_submit.png", full_page=True)
            log(f"page after submit: {page.url}")
            if page.url == before:
                log("NOTE: still on the form page, check post/after_submit.png and the messages above")
        else:
            log("DRY RUN: nothing was submitted.")
        browser.close()


if __name__ == "__main__":
    main()
