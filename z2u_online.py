"""z2u-online: keeps the z2u seller account online on GitHub Actions.

Login = cookies exported from your own browser (Cookie-Editor -> Export -> JSON),
stored in the repo secret Z2U_COOKIES. No password is ever used or printed.
The page stays open (so the site's own live connection keeps you online) and is
refreshed every few minutes. Every EXTEND_MINUTES (default 60, 0 = off) it also
presses "Extend" on every offer in Active Offers (see z2u_extend.py).
If the site's bot check blocks this GitHub server, the run ends normally so the
next run starts on a fresh server. Exits with an error (red X + GitHub email)
only if you get logged out, so you know to refresh the cookies.
"""
import json, os, random, sys, time, datetime
from playwright.sync_api import sync_playwright

# Seller Center pages first: they keep the logged-in header (online dot) and are
# less often behind the Cloudflare "Just a moment" check than the home page.
PAGES = [u for u in [os.environ.get("Z2U_URL"),
                     "https://www.z2u.com/sell/manage",
                     "https://www.z2u.com/userCenter/index",
                     "https://www.z2u.com/sellOrder/index",
                     "https://www.z2u.com/"] if u]
RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "345"))   # GitHub job limit is 360
EXTEND_MINUTES = int(os.environ.get("EXTEND_MINUTES", "60"))
BLOCK_ROTATE = int(os.environ.get("BLOCK_ROTATE", "3"))   # blocked rounds in a row -> fresh runner
RECYCLE_MINUTES = int(os.environ.get("RECYCLE_MINUTES", "60"))  # fresh tab every hour (memory)
CHROME_ARGS = ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
               "--disable-gpu", "--no-first-run", "--disable-extensions",
               "--js-flags=--max-old-space-size=512"]
MIN_WAIT, MAX_WAIT = 3 * 60, 6 * 60                       # refresh every 3-6 min
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}
LOGGED_IN = r"text=/^\s*(log ?out|sign ?out)\s*$/i"
LOGGED_OUT = r"text=/^\s*(sign ?in|log ?in)\s*$/i"


def log(msg):
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"[{now:%H:%M:%S} UTC] {msg}", flush=True)


def load_cookies():
    raw = os.environ.get("Z2U_COOKIES", "").strip()
    if not raw:
        sys.exit("Z2U_COOKIES secret is empty. See README.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit("Z2U_COOKIES is not valid JSON. Export again with Cookie-Editor -> Export -> JSON.")
    if isinstance(data, dict):
        data = data.get("cookies", [])
    out = []
    for c in data:
        if not c.get("name") or "z2u" not in str(c.get("domain", "")):
            continue
        ck = {"name": c["name"], "value": str(c.get("value", "")),
              "domain": c["domain"], "path": c.get("path") or "/",
              "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly"))}
        exp = c.get("expirationDate") or c.get("expires")
        if exp and not c.get("session"):
            ck["expires"] = float(exp)
        ss = SAMESITE.get(str(c.get("sameSite") or "").lower())
        if ss:
            ck["sameSite"] = ss
            if ss == "None":
                ck["secure"] = True
        out.append(ck)
    if not out:
        sys.exit("No z2u cookies found in Z2U_COOKIES. Export them while you are ON z2u.com.")
    log(f"loaded {len(out)} z2u cookies")
    return out


def state(page):
    """Return 'in', 'out', 'blocked' or 'unknown'."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    if "just a moment" in title or "attention required" in title:
        return "blocked"
    url = page.url.lower()
    if any(k in url for k in ("login", "signin", "sign-in", "register")):
        return "out"
    try:
        if page.locator(LOGGED_IN).count() > 0:
            return "in"
        if page.locator(LOGGED_OUT).first.is_visible(timeout=3000):
            return "out"
    except Exception:
        pass
    return "unknown"


def human_touch(page):
    try:
        page.mouse.move(random.randint(100, 1200), random.randint(100, 700), steps=random.randint(5, 20))
        page.mouse.wheel(0, random.randint(200, 900))
        time.sleep(random.uniform(1, 3))
        page.mouse.wheel(0, -random.randint(200, 900))
    except Exception:
        pass


def maybe_extend(ctx, next_at):
    """Run Extend on Active Offers when it's time. Returns the next due time."""
    if EXTEND_MINUTES <= 0 or time.time() < next_at:
        return next_at
    try:
        from z2u_extend import extend_all
        n = extend_all(ctx)
        log(f"extend round done ({n} offer(s))")
    except Exception as e:
        log(f"extend round failed: {e.__class__.__name__}")
    return time.time() + EXTEND_MINUTES * 60


def wait_challenge(page, seconds=40):
    """Give the Cloudflare 'Just a moment' check time to pass by itself."""
    end = time.time() + seconds
    st = state(page)
    while st == "blocked" and time.time() < end:
        time.sleep(4)
        human_touch(page)
        st = state(page)
    return st


def open_good_page(page, start_index=0):
    """Try the pages in PAGES (starting at start_index) until one is not blocked.
    Returns (state, index)."""
    st, idx = "blocked", start_index % len(PAGES)
    for k in range(len(PAGES)):
        idx = (start_index + k) % len(PAGES)
        try:
            page.goto(PAGES[idx], wait_until="domcontentloaded", timeout=90000)
            time.sleep(4)
            st = wait_challenge(page)
        except Exception as e:
            log(f"open {PAGES[idx]} failed: {e.__class__.__name__}")
            continue
        log(f"page {PAGES[idx].split('//')[-1]} -> {st}")
        if st != "blocked":
            return st, idx
    return st, idx


def main():
    cookies = load_cookies()
    deadline = time.time() + RUN_MINUTES * 60
    next_extend = time.time() + 60          # first Extend round 1 minute after start
    bad_out = 0
    blocked = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROME_ARGS)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 768},
                                  locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page_born = time.time()
        st, idx = open_good_page(page)
        log(f"opened, status: {st}")
        rounds = 0
        while time.time() < deadline:
            wait = random.randint(MIN_WAIT, MAX_WAIT)
            if EXTEND_MINUTES > 0:
                wait = min(wait, max(1, next_extend - time.time()))
            time.sleep(min(wait, max(1, deadline - time.time())))
            if time.time() >= deadline:
                break
            next_extend = maybe_extend(ctx, next_extend)
            if RECYCLE_MINUTES > 0 and time.time() - page_born > RECYCLE_MINUTES * 60:
                # a tab open for hours slowly eats memory; swap it for a fresh one
                try:
                    new = ctx.new_page()
                    page.close()
                    page = new
                    page_born = time.time()
                    st, idx = open_good_page(page, idx)
                    log(f"fresh tab opened, status: {st}")
                except Exception as e:
                    log(f"tab recycle problem: {e.__class__.__name__}")
            try:
                page.reload(wait_until="domcontentloaded", timeout=90000)
                time.sleep(4)
                human_touch(page)
                st = wait_challenge(page)
                if st == "blocked":
                    st, idx = open_good_page(page, idx + 1)
            except Exception as e:
                log(f"refresh problem: {e.__class__.__name__}, retry next round")
                continue
            rounds += 1
            if st == "blocked":
                blocked += 1
                log(f"WARNING: all pages blocked by the site's bot check ({blocked}/{BLOCK_ROTATE})")
                if blocked >= BLOCK_ROTATE:
                    # Not a login problem: this GitHub server's IP is being challenged.
                    # End this run normally so the next run starts on a fresh server/IP.
                    browser.close()
                    log("rotating: ending this run so the next one gets a fresh GitHub server")
                    return
                continue
            blocked = 0
            if st == "out":
                bad_out += 1
                log(f"WARNING: status = out ({bad_out}/2)")
                if bad_out >= 2:
                    browser.close()
                    sys.exit("LOGGED OUT: export fresh cookies and update the Z2U_COOKIES secret.")
            else:
                bad_out = 0
                log(f"refresh #{rounds} ok (status: {st})")
        browser.close()
    log("run finished normally, next run takes over")


if __name__ == "__main__":
    main()
