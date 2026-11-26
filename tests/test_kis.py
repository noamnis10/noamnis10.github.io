"""End-to-end tests for כיס: money math, persistence, import, backup and offline use."""
import datetime
import json
import os

import pytest

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_daily_budget_after_onboarding(app):
    app.open(); app.onboard()
    c = app.calc()
    # 2000 balance - 800 pending card - 300 cushion = 900 free over 20 days until the scholarship
    assert (c["bal"], c["avail"], c["days"], c["safe"]) == (2000, 900, 20, 45)


def test_card_purchase_is_reserved_and_undo_restores(app):
    app.open(); app.onboard()
    app.add("30", "food")
    assert app.calc()["safe"] == 15 and app.calc()["bal"] == 2000  # card: bank unchanged, money reserved
    app.add("20", "bus", method="now")
    assert app.calc()["bal"] == 1980
    app.p.click("#toastB")
    assert app.calc()["bal"] == 2000


def test_installments_only_reserve_payments_due_before_next_income(app):
    app.open(); app.onboard()
    app.add("1200", "shop", installments=6)
    c = app.calc()
    assert c["avail"] == 700  # only the first 200 is due before Dec 16


def test_validation_blocks_empty_amount(app):
    app.open(); app.onboard()
    app.p.click("#fab"); app.p.click("#save")
    assert app.p.text_content("#aerr") == "מקלידים סכום קודם"


def test_data_survives_reload_and_localstorage_loss(app):
    app.open(); app.onboard(); app.add("25"); app.add("40", method="now")
    before = app.state()
    app.p.wait_for_timeout(500)
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.state() == before
    app.p.evaluate("localStorage.clear()")
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.state() == before  # recovered from IndexedDB


def test_monthly_bill_posts_once_and_respects_delete(app):
    app.open(); app.onboard(income=None)
    app.tab("plan"); app.p.click('[data-a="add-bill"]')
    app.p.fill("#f_name", "שכר דירה"); app.p.fill("#f_amt", "1800"); app.p.fill("#f_day", "1")
    app.p.select_option("#f_method", "bank"); app.p.click("#fsave")
    app.p.wait_for_timeout(400)
    count = "Object.values(__kis.M).flat().filter(t=>(t.src||'').startsWith('bill:')).length"
    app.p.clock.set_system_time(datetime.datetime(2026, 12, 3, 9, 0))
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.evaluate(count) == 1 and app.calc()["bal"] == 200
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.evaluate(count) == 1


def test_import_card_statement_finds_missing_transactions(app):
    app.open(); app.onboard(); app.add("30", "food")
    app.tab("more")
    app.p.set_input_files("#imp", os.path.join(FIX, "max.xlsx"))
    app.p.wait_for_selector("#impgo")
    assert app.p.locator(".sheet .tile .v").all_text_contents() == ["1", "3"]
    app.p.click("#impgo"); app.p.wait_for_timeout(300)
    app.p.set_input_files("#imp", os.path.join(FIX, "cal.csv"))
    app.p.wait_for_selector("#impgo")
    assert app.p.locator(".sheet [data-pi]").count() == 2


def test_backup_file_roundtrip(app, tmp_path):
    app.open(); app.onboard(); app.add("55")
    before = json.loads(app.state())
    app.tab("more")
    with app.p.expect_download() as d:
        app.p.click('[data-a="bkf"]')
    path = tmp_path / "b.json"; d.value.save_as(path)
    app.p.click('[data-a="wipe"]'); app.p.fill("#wi", "מחק"); app.p.click("#wgo")
    app.p.wait_for_selector(".ob h1")
    app.onboard(balance="1", card_due="0", income=None)
    app.tab("more"); app.p.set_input_files("#rsf", str(path)); app.p.wait_for_timeout(300)
    after = json.loads(app.state())
    assert after[1] == before[1] and after[0]["anchor"] == before[0]["anchor"]


def test_works_offline_after_first_visit(app, ctx):
    app.open(); app.onboard()
    app.p.wait_for_function("navigator.serviceWorker.controller || (location.reload(), false)", timeout=10000)
    ctx.set_offline(True)
    app.p.reload(); app.p.wait_for_selector(".hero")
    ctx.set_offline(False)
