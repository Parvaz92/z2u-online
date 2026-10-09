"""z2u-online: keeps the z2u seller account online on GitHub Actions.

Login = cookies exported from your own browser (Cookie-Editor -> Export -> JSON),
stored in the repo secret Z2U_COOKIES. No password is ever used or printed.
The page stays open (so the site's own live connection keeps you online) and is
refreshed every few minutes. Exits with an error (red X + GitHub email) if you
get logged out, so you know to refresh the cookies.
"""
import json, os, random, sys, time, datetime
from playwright.sync_api import sync_playwright

START_URL = os.environ.get("Z2U_URL") or "https://www.z2u.com/"
RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "345"))   # GitHub job limit is 360
MIN_WAIT, MAX_WAIT = 3 * 60, 6 * 60                       # refresh every 3-6 min
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}
LOGGED_IN = r"text=/^\s*(log ?out|sign ?out)\s*$/i"
LOGGED_OUT = r"text=/^\s*(sign ?in|log ?in)\s*$/i"


def log(msg):
    print(f"[{datetime.datetime.utcnow():%H:%M:%S} UTC] {msg}", flush=True)


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


def main():
    cookies = load_cookies()
    deadline = time.time() + RUN_MINUTES * 60
    bad = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 768},
                                  locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto(START_URL, wait_until="domcontentloaded", timeout=90000)
        time.sleep(5)
        log(f"opened, status: {state(page)}")
        rounds = 0
        while time.time() < deadline:
            time.sleep(min(random.randint(MIN_WAIT, MAX_WAIT), max(1, deadline - time.time())))
            if time.time() >= deadline:
                break
            try:
                page.reload(wait_until="domcontentloaded", timeout=90000)
                time.sleep(4)
                human_touch(page)
                st = state(page)
            except Exception as e:
                log(f"refresh problem: {e.__class__.__name__}, retry next round")
                continue
            rounds += 1
            if st in ("out", "blocked"):
                bad += 1
                log(f"WARNING: status = {st} ({bad}/2)")
                if bad >= 2:
                    browser.close()
                    if st == "out":
                        sys.exit("LOGGED OUT: export fresh cookies and update the Z2U_COOKIES secret.")
                    sys.exit("BLOCKED by the site's bot check from GitHub servers.")
            else:
                bad = 0
                log(f"refresh #{rounds} ok (status: {st})")
        browser.close()
    log("run finished normally, next run takes over")


if __name__ == "__main__":
    main()
