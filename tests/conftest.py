"""Shared fixtures: serve the repo over localhost and open the app in a phone-sized browser."""
import datetime
import functools
import http.server
import os
import socketserver
import threading

import pytest
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.datetime(2026, 11, 26, 15, 0)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def base_url():
    handler = functools.partial(_Quiet, directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}/kis/"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        exe = os.environ.get("CHROME_PATH")
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def ctx(browser):
    c = browser.new_context(viewport={"width": 390, "height": 844}, locale="he-IL",
                            timezone_id="Asia/Jerusalem", accept_downloads=True)
    c.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    yield c
    c.close()


class App:
    """Small page-object for driving the app like a user."""

    def __init__(self, page, url):
        self.p, self.url, self.errors = page, url, []
        page.on("pageerror", lambda e: self.errors.append(str(e)))

    def open(self, when=TODAY):
        self.p.clock.install(time=when)
        self.p.goto(self.url)
        self.p.wait_for_selector("#app h1, .hero")

    def onboard(self, balance="2000", card_due="800", income=("מלגה", "3000", "2026-12-16"), cushion="300"):
        p = self.p
        p.fill("#o1", balance); p.click("#on")
        p.click('[data-bd="10"]'); p.fill("#o8", card_due); p.click("#on")
        if income:
            p.fill("#o5", income[0]); p.fill("#o4", income[1]); p.fill("#o6", income[2]); p.click("#on")
        else:
            p.click("#skip")
        p.click(f'[data-cu="{cushion}"]'); p.click("#on")
        p.wait_for_selector(".hero")

    def add(self, amount, cat="food", method=None, installments=1, note=None):
        p = self.p
        p.click("#fab"); p.wait_for_selector("#save")
        for ch in amount:
            p.click(f'.pad [data-k="{ch}"]')
        p.click(f'[data-cat="{cat}"]')
        if method:
            p.click(f'[data-m="{method}"]')
        for _ in range(installments - 1):
            p.click('[data-n="1"]')
        if note:
            p.fill("#nt", note)
        p.click("#save")
        p.wait_for_selector("#sheet", state="hidden")

    def calc(self):
        return self.p.evaluate("(()=>{const c=__kis.compute();return {bal:c.bal,avail:c.avail,daily:c.daily,"
                               "safe:c.safe,days:c.daysLeft,st:c.st,H:c.H}})()")

    def state(self):
        return self.p.evaluate("JSON.stringify([__kis.S,__kis.M])")

    def tab(self, name):
        self.p.click(f'nav [data-v="{name}"]')


@pytest.fixture
def app(ctx, base_url):
    a = App(ctx.new_page(), base_url)
    yield a
    assert not a.errors, a.errors
