"""Real captures for the site images (docs/img/*.webp), replacing the SVG placeholders.

    pip install playwright pillow && playwright install chromium
    python scripts/site/shoot.py                      # everything it can, in order
    python scripts/site/shoot.py --only log-flag      # one step (comma-separated list allowed)
    python scripts/site/shoot.py --list               # what each step needs

What the operator provides (once):

  DISCORD_TOKEN        the test bot's token (Developer Portal -> Bot). The bot must already be invited to the test
                       guild with the permissions the privacy page lists (View Channels, Send Messages, Manage
                       Channels to create #jevmod-log, Add Reactions, Read Message History, Message Content intent).
  TYPESAFE_API_KEY     a Jev key; the bot really judges the five example messages.
  TEST_GUILD_ID        id of a throwaway guild (Developer Mode -> right click -> Copy Server ID).
  TEST_CHANNEL_ID      id of a text channel in it where the examples get posted (its topic is "general chat").
  DISCORD_PROFILE_DIR  a directory for a persistent Chromium profile. First run: the browser opens, you log in to
                       https://discord.com/login by hand (2FA included) and set Settings -> Appearance -> Light,
                       then press Enter in the terminal. The profile is reused by later runs; never commit it.
  BROWSER_CHANNEL      optional: "msedge" or "chrome" to use an installed browser instead of Playwright's Chromium.

Why the examples are typed through the web client and not posted through the API: `on_message` ignores bot
authors (discord_bot.py, `if msg.author.bot`), so a message sent with any bot token is never judged, and using a
user token against the HTTP API breaks Discord's terms. The logged-in profile is a user account, so Playwright
types the five messages in the composer exactly as a member would. With `--no-post` the script prints them for
you to paste instead and just waits for the log embed.

Steps and what each one captures (2x device scale factor, light theme, cropped to the message, fitted onto a
canvas of the exact size the page references, then WebP <= 200 KB):

  log-flag         1600x1000  the embed `scam  p=0.99  ->  flag` in #jevmod-log (title, message, author, channel,
                              footer with the three top scores and the reaction hint, the bot's own ❌ ✅)
  reaction-nudge   1600x600   the moderator's ❌ on that embed and the reply "noted: threshold for **scam** is now
                              0.78" (0.75 default + 0.03)
  mod-status       1600x1200  the ephemeral reply to /mod status after the policy was set to `scam delete 0.70`
                              plus one rule ("politics"), so the capture matches the copy of the #control section
  admin-panel      2400x1400  /admin of a local `jevmod hosted` with six seeded tenants (no Discord needed)

The Discord steps share one bot process and one temporary JEVMOD_DB; nothing touches your real database. The
script never runs a step whose inputs are missing: it says which env var it lacks and moves on, and ends with
the list of things it could not automate.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IMG = ROOT / "docs" / "img"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from img_to_webp import to_webp  # noqa: E402

SIZES = {
    "log-flag": (1600, 1000),
    "reaction-nudge": (1600, 600),
    "mod-status": (1600, 1200),
    "admin-panel": (2400, 1400),
}
ORDER = ("log-flag", "reaction-nudge", "mod-status", "admin-panel")
DISCORD_ENV = ("DISCORD_TOKEN", "TYPESAFE_API_KEY", "TEST_GUILD_ID", "TEST_CHANNEL_ID", "DISCORD_PROFILE_DIR")
NEEDS = {
    "log-flag": DISCORD_ENV,
    "reaction-nudge": DISCORD_ENV,
    "mod-status": DISCORD_ENV,
    "admin-panel": (),
}
# The five chips of the live demo on the landing page, in the same order.
EXAMPLES = (
    "FREE NITRO for the first 100!! claim at discord-gifts.ru/nitro",
    "you're a worthless idiot and everyone here hates you, just leave",
    "Anyone know if the patch fixed the inventory bug?",
    "I don't want to be here anymore. nobody would notice if I was gone",
    "Hat jemand Lust auf eine Runde heute Abend? Brauchen noch einen Heiler.",
)
ADMIN_PORT = int(os.environ.get("SHOOT_ADMIN_PORT", "8765"))
ADMIN_TOKEN = "shoot"
PAD = 24  # CSS px of chat kept around the cropped message
MANUAL: list[str] = []  # everything the operator has to do by hand, printed at the end


# ---------------------------------------------------------------- helpers
def say(msg: str) -> None:
    print(f"[shoot] {msg}", flush=True)


def missing_env(step: str) -> list[str]:
    return [v for v in NEEDS[step] if not os.environ.get(v)]


def wait_for(pred: Callable[[], Any], timeout: float, what: str, every: float = 1.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(every)
    raise TimeoutError(f"gave up after {timeout:.0f}s waiting for {what}")


def fit_and_convert(png: Path, name: str) -> Path:
    """Centre the capture on a #FAFAFA canvas of the exact page size (never upscale), save PNG + WebP."""
    from PIL import Image

    w, h = SIZES[name]
    with Image.open(png) as im:
        im = im.convert("RGB")
        if im.width > w or im.height > h:
            im.thumbnail((w, h), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), "#FAFAFA")
        canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    out_png = IMG / f"{name}.png"
    canvas.save(out_png, "PNG", optimize=True)
    webp, n, q = to_webp(out_png, IMG / f"{name}.webp", 200)
    say(f"{webp.relative_to(ROOT)}  {n / 1024:.1f} KB  q={q}  ({w}x{h})")
    return webp


@contextlib.contextmanager
def process(args: list[str], env: dict[str, str], name: str) -> Iterator[subprocess.Popen[bytes]]:
    say(f"starting {name}: {' '.join(args)}")
    p = subprocess.Popen(args, env={**os.environ, **env}, cwd=ROOT)
    try:
        time.sleep(2)
        if p.poll() is not None:
            raise RuntimeError(f"{name} exited with {p.returncode} right after start; read its output above")
        yield p
    finally:
        p.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            p.wait(10)
        if p.poll() is None:
            p.kill()


def jevmod(role: str) -> list[str]:
    return [sys.executable, "-m", "jevmod", role]


# ---------------------------------------------------------------- Discord side
class Discord:
    """One bot process on a temp DB plus the operator's logged-in browser profile."""

    def __init__(self, pw: Any, workdir: Path) -> None:
        from jevmod.core import Store

        self.guild = os.environ["TEST_GUILD_ID"]
        self.channel = os.environ["TEST_CHANNEL_ID"]
        self.tenant = f"discord:{self.guild}"
        self.db = workdir / "jevmod-shoot.sqlite"
        self.store = Store(self.db)  # same file as the bot; SQLite handles the two writers
        self.bot = process(jevmod("discord"), {"JEVMOD_DB": str(self.db), "JEVMOD_KEEP_TEXT_CHARS": "80"}, "bot")
        self.bot.__enter__()
        profile = Path(os.environ["DISCORD_PROFILE_DIR"]).expanduser()
        first_login = not (profile / "Default").exists()
        kw: dict[str, Any] = {}
        if os.environ.get("BROWSER_CHANNEL"):
            kw["channel"] = os.environ["BROWSER_CHANNEL"]
        self.ctx = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,  # Discord serves a captcha to headless clients; a visible window with a profile works
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,
            color_scheme="light",
            **kw,
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        if first_login:
            self.page.goto("https://discord.com/login")
            MANUAL.append("first run: logged in to Discord by hand in the Playwright window (profile now saved)")
            input("[shoot] log in to Discord in the browser window, set Appearance -> Light, then press Enter... ")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.ctx.close()
        self.bot.__exit__(None, None, None)

    # ---- navigation
    def open(self, channel_id: str) -> None:
        self.page.goto(f"https://discord.com/channels/{self.guild}/{channel_id}", wait_until="domcontentloaded")
        self.page.wait_for_selector("div[role='textbox']", timeout=60_000)
        self.page.wait_for_timeout(1500)
        theme = self.page.evaluate("document.documentElement.className")
        if "theme-light" not in theme:
            raise RuntimeError("Discord is not in the light theme: Settings -> Appearance -> Light, then rerun")

    def type_message(self, text: str) -> None:
        box = self.page.locator("div[role='textbox']").first
        box.click()
        self.page.keyboard.type(text, delay=5)
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(800)

    def slash(self, command: str) -> None:
        """Type a slash command; Enter picks it in the autocomplete, Enter again sends it."""
        box = self.page.locator("div[role='textbox']").first
        box.click()
        self.page.keyboard.type(command, delay=20)
        self.page.wait_for_timeout(800)
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(400)
        self.page.keyboard.press("Enter")

    def log_channel_id(self) -> str:
        return str(wait_for(lambda: self.store.get_meta(self.tenant).get("log_channel"), 90, "#jevmod-log to exist"))

    def message(self, text: str) -> Any:
        """The chat <li> whose content contains `text`, waited for."""
        loc = self.page.locator("li[id^='chat-messages-']", has_text=text).last
        loc.wait_for(timeout=90_000)
        return loc

    def capture(self, locators: list[Any], out: Path) -> None:
        """Screenshot the union of the locators' boxes plus PAD, on the chat background."""
        boxes = [loc.bounding_box() for loc in locators]
        if any(b is None for b in boxes):
            raise RuntimeError("an element to capture is not visible")
        x0 = max(0, min(b["x"] for b in boxes) - PAD)
        y0 = max(0, min(b["y"] for b in boxes) - PAD)
        x1 = max(b["x"] + b["width"] for b in boxes) + PAD
        y1 = max(b["y"] + b["height"] for b in boxes) + PAD
        # hide the hover toolbar so it does not sit on top of the embed
        self.page.mouse.move(5, 5)
        self.page.wait_for_timeout(300)
        self.page.screenshot(path=str(out), clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})

    # ---- steps
    def post_examples(self, post: bool) -> None:
        self.open(self.channel)
        if post:
            for text in EXAMPLES:
                self.type_message(text)
                time.sleep(2.5)  # the batcher flushes every 2 s; one message per batch keeps the embeds tidy
        else:
            print("\n".join(f"  paste: {t}" for t in EXAMPLES))
            MANUAL.append("posted the five example messages by hand (--no-post)")
        wait_for(
            lambda: any(r["category"] == "scam" for r in self.store.recent_decisions(self.tenant, 10)),
            120,
            "the bot to log a scam decision (is TYPESAFE_API_KEY valid? is the bot in the guild?)",
        )

    def scam_embed(self) -> Any:
        self.open(self.log_channel_id())
        return self.message("scam  p=")

    def step_log_flag(self, post: bool, tmp: Path) -> None:
        self.post_examples(post)
        li = self.scam_embed()
        li.scroll_into_view_if_needed()
        self.capture([li], tmp / "log-flag.png")
        fit_and_convert(tmp / "log-flag.png", "log-flag")

    def step_reaction_nudge(self, tmp: Path) -> None:
        li = self.scam_embed()
        before = self.store.get_policy(self.tenant).thresholds.get("scam", 0.9)
        li.hover()
        li.locator("div[role='button'][aria-label*='❌']").first.click()
        reply = self.message("noted: threshold for")
        after = self.store.get_policy(self.tenant).thresholds["scam"]
        say(f"scam threshold {before:.2f} -> {after:.2f}")
        reactions = li.locator("div[class*='reactions']").first
        self.capture([reactions, reply], tmp / "reaction-nudge.png")
        fit_and_convert(tmp / "reaction-nudge.png", "reaction-nudge")

    def step_mod_status(self, tmp: Path) -> None:
        p = self.store.get_policy(self.tenant)
        p.set_category("scam", "delete", 0.70)  # the example command of the #control section
        p.set_rule("politics", "No politics. News about the game is fine.")
        self.store.save_policy(self.tenant, p)
        self.open(self.channel)
        self.slash("/mod status")
        li = self.message("judged this month")
        self.capture([li], tmp / "mod-status.png")
        fit_and_convert(tmp / "mod-status.png", "mod-status")


# ---------------------------------------------------------------- admin side
def seed_admin(db: Path) -> None:
    """Six tenants: two on Pro with a subscription, four on Free, usage spread so the table is not flat."""
    from jevmod.core import Store

    s = Store(db)
    rows = (  # tenant, plan, judged, tokens (about 1,005 per request, one request per message)
        ("discord:821344709938162034", "pro", 12_480, 12_542_400),
        ("discord:501777283054611190", "free", 3_912, 3_931_560),
        ("discord:229904108827193501", "pro", 2_106, 2_116_530),
        ("discord:935466210083447209", "free", 640, 643_200),
        ("discord:118033957726009144", "free", 88, 88_440),
        ("discord:660211475539288013", "free", 0, 0),
    )
    for tenant, plan, judged, tokens in rows:
        s.set_plan(tenant, plan)
        if judged:
            s.add_usage(tenant, judged, judged, tokens)
        if plan == "pro":
            s.set_subscription(
                tenant,
                customer_id="cus_shoot",
                subscription_id="sub_shoot",
                price_id="price_shoot",
                status="active",
                current_period_end=time.time() + 14 * 86_400,
            )


def step_admin_panel(pw: Any, tmp: Path) -> None:
    db = tmp / "jevmod-admin.sqlite"
    seed_admin(db)
    env = {
        "JEVMOD_DB": str(db),
        "JEVMOD_DEMO_DB": str(tmp / "demo.sqlite"),
        "JEVMOD_ADMIN_TOKEN": ADMIN_TOKEN,
        "JEVMOD_MONTHLY_QUOTA": "5000",
        "PORT": str(ADMIN_PORT),
        "TYPESAFE_API_KEY": os.environ.get("TYPESAFE_API_KEY", "unused-for-the-admin-capture"),
    }
    url = f"http://127.0.0.1:{ADMIN_PORT}/admin?token={ADMIN_TOKEN}"

    def up() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 (local URL)
                return r.status == 200
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            return False

    with process(jevmod("hosted"), env, "hosted"):
        wait_for(up, 30, f"{url} to answer 200")
        w, h = SIZES["admin-panel"]
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": w // 2, "height": h // 2}, device_scale_factor=2)
            page.goto(url)
            page.wait_for_selector("table tbody tr")
            page.wait_for_timeout(500)
            page.screenshot(path=str(tmp / "admin-panel.png"))  # viewport = exactly 2400x1400 at 2x
        finally:
            browser.close()
    fit_and_convert(tmp / "admin-panel.png", "admin-panel")


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="real captures for docs/img; see the module docstring")
    ap.add_argument("--only", default="all", help="comma-separated: " + ", ".join(ORDER))
    ap.add_argument("--no-post", action="store_true", help="do not type the examples; wait for you to paste them")
    ap.add_argument("--keep", action="store_true", help="keep the temp dir (DB, raw PNGs) for inspection")
    ap.add_argument("--list", action="store_true", help="print steps and their env vars, then exit")
    a = ap.parse_args(argv)
    if a.list:
        for step in ORDER:
            print(f"{step:15s} {SIZES[step][0]}x{SIZES[step][1]}  needs: {', '.join(NEEDS[step]) or 'nothing'}")
        return 0
    steps = list(ORDER) if a.only == "all" else [s.strip() for s in a.only.split(",")]
    unknown = [s for s in steps if s not in SIZES]
    if unknown:
        ap.error(f"unknown step(s) {unknown}; choose from {', '.join(ORDER)}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        say("pip install playwright pillow && playwright install chromium")
        return 2
    IMG.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="jevmod-shoot-"))
    done: list[str] = []
    skipped: list[str] = []
    discord: Discord | None = None
    try:
        with sync_playwright() as pw:
            for step in steps:
                lack = missing_env(step)
                if lack:
                    skipped.append(f"{step}: missing env {', '.join(lack)}")
                    continue
                say(f"--- {step}")
                try:
                    if step == "admin-panel":
                        step_admin_panel(pw, tmp)
                    else:
                        discord = discord or Discord(pw, tmp)
                        if step == "log-flag":
                            discord.step_log_flag(not a.no_post, tmp)
                        elif step == "reaction-nudge":
                            if "log-flag" not in done:
                                discord.post_examples(not a.no_post)
                            discord.step_reaction_nudge(tmp)
                        elif step == "mod-status":
                            discord.step_mod_status(tmp)
                    done.append(step)
                except Exception as exc:  # keep going: the report at the end says what failed and why
                    skipped.append(f"{step}: {type(exc).__name__}: {exc}")
    finally:
        if discord:
            discord.close()
        if a.keep:
            say(f"kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("captured:      " + (", ".join(done) or "nothing"))
    for line in skipped:
        print("not captured:  " + line)
    if MANUAL:
        print("done by hand:  " + "; ".join(MANUAL))
    print(
        "always by hand: inviting the bot to the test guild with the right permissions; logging in to Discord once "
        "into DISCORD_PROFILE_DIR; the light theme (an account setting); checking each capture with your own eyes "
        "before replacing the placeholder SVG references in the pages."
    )
    return 0 if done and not skipped else 1


if __name__ == "__main__":
    sys.exit(main())
