"""Apple Pay file import: line parsing, stable ids, de-duplication, reminder, guide and data compatibility."""
import datetime
import json
import os

import pytest

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "fixtures")
DOCS = os.path.join(os.path.dirname(HERE), "docs", "apple-pay.md")

WOLT = "2026-11-24T13:00:00+02:00;64.50;Wolt"
SUPER_PHARM = "2026-11-21;1,120.00;סופר פארם"
COFFEE = "2026-11-26T08:12:00+02:00;₪45.90;קפה גרג"
SUPERSAL = "2026-11-25T19:40:00+02:00;₪120.00;שופרסל דיל"


def parse(app, text):
    return app.p.evaluate("t=>__kis.parseAp(t)", text)


def pick(app, lines):
    app.p.set_input_files("#apf", files={"name": "kis-applepay.txt", "mimeType": "text/plain",
                                         "buffer": "\n".join(lines).encode("utf-8")})


def tiles(app):
    app.p.wait_for_selector("#sheet .tile")
    return app.p.locator("#sheet .tile .v").all_text_contents()


def ap_tx(app):
    return app.p.evaluate("Object.values(__kis.M).flat().filter(t=>t.src==='ap')")


def confirm(app):
    app.p.click("#apadd")
    app.p.wait_for_selector("#sheet", state="hidden")


# ---------- parsing ----------

VALID = [
    ("2026-11-26T14:03:00+02:00;₪45.90;קפה גרג", "2026-11-26", 45.9, "קפה גרג"),
    ("2026-11-26;₪1,234.50;Wolt", "2026-11-26", 1234.5, "Wolt"),
    ("2026-11-26T09:15:00Z;12;Super-Pharm", "2026-11-26", 12, "Super-Pharm"),
    ("2026-11-25T22:30:00Z;99.9;לילה", "2026-11-26", 99.9, "לילה"),  # 00:30 local time on the 26th
    ("2026-11-26 08:00;1,234.5 ₪;שם;עם;נקודה-פסיק", "2026-11-26", 1234.5, "שם;עם;נקודה-פסיק"),
    ("2026-11-26;12,50;Café   Roma", "2026-11-26", 12.5, "Café Roma"),
    ("‏2026-11-26;‎₪45;‏קפה", "2026-11-26", 45, "קפה"),
    ("2026-11-26;45;", "2026-11-26", 45, "Apple Pay"),
    ("2026-11-26;₪ 1.234,56;מסעדה", "2026-11-26", 1234.56, "מסעדה"),
    ('2026-11-26;45 ש"ח;פיצה', "2026-11-26", 45, "פיצה"),
    ("  2026-11-26 ; 7 ; Aroma Café ", "2026-11-26", 7, "Aroma Café"),
]


@pytest.mark.parametrize("line,d,amt,name", VALID)
def test_parses_valid_line(app, line, d, amt, name):
    app.open()
    r = parse(app, line)
    assert r["bad"] == [] and len(r["rows"]) == 1
    row = r["rows"][0]
    assert (row["d"], row["amt"], row["name"]) == (d, amt, name)
    assert row["id"].startswith("ap_")


INVALID = [
    "garbage", "2026-11-26;45", "2026-13-45;45;x", "2026-02-31;45;x", "26/11/2026;45;x",
    "2026-11-26;abc;x", "2026-11-26;;x", "2026-11-26;-45;x", "2026-11-26;0;x", "2026-11-26;$12;x",
    "2026-11-26;1,2,3;x", "2026-11-26;45.5.5;x", "2099-01-01;5;x", "2019-12-31;5;x", ";45;x",
    "2026-11-26T25:00:00;45;x", "קפה;45;2026-11-26",
]


@pytest.mark.parametrize("line", INVALID)
def test_rejects_corrupt_line(app, line):
    app.open()
    r = parse(app, line)
    assert r["rows"] == [] and len(r["bad"]) == 1


def test_mixed_file_with_bom_crlf_blank_and_corrupt_lines(app):
    app.open()
    text = "﻿" + "\r\n".join([COFFEE, "", "שורה שבורה", SUPERSAL, "   ", "2026-13-01;5;x", WOLT]) + "\r\n"
    r = parse(app, text)
    assert [x["name"] for x in r["rows"]] == ["קפה גרג", "שופרסל דיל", "Wolt"]
    assert [b["n"] for b in r["bad"]] == [3, 6]  # blank lines are ignored, not counted


def test_ids_are_stable_and_distinguish_rows(app):
    app.open()
    a = parse(app, COFFEE)["rows"][0]["id"]
    assert parse(app, COFFEE)["rows"][0]["id"] == a
    # amount formatting and spacing do not change the id
    assert parse(app, "2026-11-26T08:12:00+02:00;45.9;קפה   גרג")["rows"][0]["id"] == a
    for other in ["2026-11-26T08:12:01+02:00;₪45.90;קפה גרג", "2026-11-26T08:12:00+02:00;₪45.91;קפה גרג",
                  "2026-11-26T08:12:00+02:00;₪45.90;קפה גרג 2"]:
        assert parse(app, other)["rows"][0]["id"] != a
    # identical lines in one file stay distinct, and the first keeps the id it has alone
    ids = [r["id"] for r in parse(app, COFFEE + "\n" + COFFEE)["rows"]]
    assert len(set(ids)) == 2 and ids[0] == a


# ---------- import flow ----------

def test_import_adds_card_expenses_with_categories_and_undo(app):
    app.open(); app.onboard()
    before = app.calc()
    app.tab("more"); pick(app, [COFFEE, SUPERSAL, WOLT, "שורה שבורה"])
    assert tiles(app) == ["0", "3"]
    assert "דולגו" in app.p.text_content("#sheet")
    confirm(app)
    tx = ap_tx(app)
    assert sorted(t["cat"] for t in tx) == ["food", "food", "super"]
    assert all(t["m"] == "card" and t["t"] == "exp" and t["id"].startswith("ap_") for t in tx)
    assert sorted(t["amt"] for t in tx) == [45.9, 64.5, 120]
    c = app.calc()
    assert c["bal"] == before["bal"] and c["avail"] == pytest.approx(before["avail"] - 230.4)
    assert "3" in app.p.text_content("#toastT")
    app.p.click("#toastB")
    assert ap_tx(app) == [] and app.p.evaluate("__kis.S.apple.seen.length") == 0
    pick(app, [COFFEE, SUPERSAL, WOLT])
    assert tiles(app) == ["0", "3"]  # undo also forgets the rows, so they can be imported again


def test_same_file_twice_adds_nothing_and_deleted_rows_stay_deleted(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [COFFEE, SUPERSAL]); tiles(app); confirm(app)
    assert len(ap_tx(app)) == 2
    pick(app, [COFFEE, SUPERSAL])
    assert tiles(app) == ["2", "0"]
    assert app.p.locator("#apadd").count() == 0
    app.p.click("#sheet [data-close].btn"); app.p.wait_for_selector("#sheet", state="hidden")
    assert len(ap_tx(app)) == 2
    # delete one payment, choose the same file again: it must not come back
    app.tab("list"); app.p.click("[data-tx]"); app.p.click("#del")
    app.p.wait_for_selector("#sheet", state="hidden")
    assert len(ap_tx(app)) == 1
    app.tab("more"); pick(app, [COFFEE, SUPERSAL])
    assert tiles(app) == ["2", "0"]
    assert len(ap_tx(app)) == 1


def test_identical_lines_in_one_file_are_both_imported_once(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [COFFEE, COFFEE]); assert tiles(app) == ["0", "2"]; confirm(app)
    assert len(ap_tx(app)) == 2
    pick(app, [COFFEE, COFFEE]); assert tiles(app) == ["2", "0"]


def test_unchecked_rows_are_skipped_and_not_offered_again(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [COFFEE, SUPERSAL]); tiles(app)
    app.p.uncheck('[data-pi="0"]')
    assert "1" in app.p.text_content("#apadd")
    confirm(app)
    assert len(ap_tx(app)) == 1
    pick(app, [COFFEE, SUPERSAL])
    assert tiles(app) == ["2", "0"]


def test_no_duplicates_against_credit_statement_import(app):
    app.open(); app.onboard(); app.tab("more")
    app.p.set_input_files("#imp", os.path.join(FIX, "cal.csv"))
    app.p.wait_for_selector("#impgo"); app.p.click("#impgo"); app.p.wait_for_selector("#sheet", state="hidden")
    far_date = "2026-11-10;64.50;Wolt"        # same amount, 14 days away
    far_amt = "2026-11-24;66.50;Wolt"         # same day, 2 shekels away
    pick(app, [WOLT, SUPER_PHARM, far_date, far_amt])  # SUPER_PHARM is a day after the statement row
    assert tiles(app) == ["2", "2"]
    confirm(app)
    assert sorted(t["amt"] for t in ap_tx(app)) == [64.5, 66.5]


def test_statement_import_after_apple_pay_finds_nothing_missing(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [WOLT, SUPER_PHARM]); tiles(app); confirm(app)
    app.p.set_input_files("#imp", os.path.join(FIX, "cal.csv"))
    app.p.wait_for_selector("#sheet .tile")
    assert app.p.locator("#sheet .tile .v").all_text_contents() == ["2", "0"]
    assert app.p.locator("#impgo").count() == 0


def test_manual_entry_is_not_duplicated(app):
    app.open(); app.onboard()
    app.add("45.9", "food")  # same day as the Apple Pay row, typed by hand
    app.tab("more"); pick(app, [COFFEE, SUPERSAL])
    assert tiles(app) == ["1", "1"]


def test_empty_or_unreadable_file_gives_guidance(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, ["", "לא שורה", "2026-11-26;45"])
    app.p.wait_for_selector("#sheet .code")
    assert "אף שורה תקינה" in app.p.text_content("#sheet")
    assert app.p.locator("#apadd").count() == 0
    assert app.p.evaluate("__kis.S.apple.last") == 0


# ---------- reminder + settings ----------

def test_home_reminder_only_when_enabled_and_stale(app):
    app.open(); app.onboard()
    app.p.clock.set_system_time(datetime.datetime(2026, 11, 30, 9, 0))
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.locator("#aprem").count() == 0  # feature off: no reminder however old

    app.tab("more")
    assert "כבוי" in app.p.text_content('[data-set="apple"]')
    app.p.click('[data-set="apple"]'); app.p.check("#f_apple"); app.p.click("#fsave")
    app.p.wait_for_selector("#sheet", state="hidden")
    assert "פועל" in app.p.text_content('[data-set="apple"]')

    app.p.clock.set_system_time(datetime.datetime(2026, 12, 1, 9, 0))
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.locator("#aprem").count() == 0  # one day since enabling

    app.p.clock.set_system_time(datetime.datetime(2026, 12, 3, 9, 30))
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.locator("#aprem").count() == 1
    assert app.p.locator("#aprem .btn").bounding_box()["height"] >= 44

    pick(app, ["2026-12-02;10;קפה"]); tiles(app); confirm(app)
    app.p.reload(); app.p.wait_for_selector(".hero")
    assert app.p.locator("#aprem").count() == 0  # reminder cleared by importing


# ---------- guide + docs ----------

def test_guide_in_app_and_docs_share_the_same_sample(app):
    app.open(); app.onboard(); app.tab("more")
    app.p.click('[data-a="apguide"]'); app.p.wait_for_selector("#sheet .guide")
    sheet = app.p.text_content("#sheet")
    sample = app.p.evaluate("__kis.AP_SAMPLE")
    assert "kis-applepay.txt" in sheet and "ISO 8601" in sheet and sample in sheet
    assert len(parse(app, sample)["rows"]) == 1
    docs = open(DOCS, encoding="utf-8").read()
    assert sample in docs and "kis-applepay.txt" in docs
    for line in docs.splitlines():  # every example line shown in the docs must parse
        if line.startswith("2026-"):
            assert len(parse(app, line)["rows"]) == 1


# ---------- accessibility ----------

def test_new_controls_are_at_least_44px(app):
    app.open(); app.onboard(); app.tab("more")
    h = lambda sel: app.p.evaluate("s=>[...document.querySelectorAll(s)].map(e=>e.getBoundingClientRect().height)", sel)
    heights = app.p.evaluate("""()=>{const c=document.querySelector('.card:has(#apf)');
        return [...c.querySelectorAll('button,label.btn')].map(e=>e.getBoundingClientRect().height)}""")
    assert len(heights) == 2 and min(heights) >= 44
    app.p.click('[data-a="apguide"]'); app.p.wait_for_selector("#sheet .guide")
    assert min(h("#sheet button")) >= 44
    app.p.click("#sheet [data-close].btn"); app.p.wait_for_selector("#sheet", state="hidden")
    pick(app, [COFFEE]); tiles(app)
    assert min(h("#sheet button")) >= 44


# ---------- existing data is preserved ----------

def test_v1_data_without_apple_field_loads_unchanged(app, ctx):
    fixture = json.load(open(os.path.join(FIX, "v1_state.json"), encoding="utf-8"))
    raw = json.dumps(json.dumps(fixture, ensure_ascii=False))
    ctx.add_init_script(f"if(!localStorage.getItem('kis.v1'))localStorage.setItem('kis.v1',{raw})")
    assert "apple" not in fixture["S"]
    app.open()
    app.p.wait_for_selector(".hero")
    S, M = json.loads(app.state())
    assert S.pop("apple") == {"on": False, "last": 0, "seen": []}
    assert S == fixture["S"] and M == fixture["M"]
    # keep working on the old data: import a payment, then everything old is still there
    app.tab("more"); pick(app, [COFFEE]); tiles(app); confirm(app)
    app.p.wait_for_timeout(500)
    stored = app.p.evaluate("JSON.parse(localStorage.getItem('kis.v1'))")
    old_ids = {t["id"] for txs in fixture["M"].values() for t in txs}
    assert old_ids <= {t["id"] for txs in stored["M"].values() for t in txs}
    assert len(ap_tx(app)) == 1
    for k in ("bills", "incomes", "sinks", "vouchers", "debts", "log", "anchor", "cushion"):
        assert stored["S"][k] == fixture["S"][k]


def test_apple_pay_state_survives_backup_roundtrip(app, tmp_path):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [COFFEE]); tiles(app); confirm(app)
    before = app.p.evaluate("JSON.stringify(__kis.S.apple)")
    with app.p.expect_download() as d:
        app.p.click('[data-a="bkf"]')
    path = tmp_path / "b.json"; d.value.save_as(path)
    app.p.click('[data-a="wipe"]'); app.p.fill("#wi", "מחק"); app.p.click("#wgo")
    app.p.wait_for_selector(".ob h1")
    app.onboard(balance="1", card_due="0", income=None)
    app.tab("more"); app.p.set_input_files("#rsf", str(path)); app.p.wait_for_timeout(300)
    assert app.p.evaluate("JSON.stringify(__kis.S.apple)") == before
    pick(app, [COFFEE])
    assert tiles(app) == ["1", "0"]


def test_identical_payment_appended_later_is_not_mistaken_for_a_duplicate(app):
    app.open(); app.onboard(); app.tab("more")
    pick(app, [COFFEE]); tiles(app); confirm(app)
    pick(app, [COFFEE, COFFEE])  # a second identical purchase was appended to the file
    assert tiles(app) == ["1", "1"]
    confirm(app)
    assert len(ap_tx(app)) == 2
