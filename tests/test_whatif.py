"""'מה אם?' simulator: never touches real data, matches a real add, installments hurt less."""
import pytest


def fill(app, amount, cat="food", method=None, installments=1):
    """Type a purchase into the add sheet like a user, without saving."""
    p = app.p
    p.click("#fab"); p.wait_for_selector("#save")
    for ch in amount:
        p.click(f'.pad [data-k="{ch}"]')
    p.click(f'[data-cat="{cat}"]')
    if method:
        p.click(f'[data-m="{method}"]')
    for _ in range(installments - 1):
        p.click('[data-n="1"]')


def whatif(app, *a, **kw):
    fill(app, *a, **kw)
    app.p.click("#whatif")
    app.p.wait_for_selector("#simfig")


def val(app, key):
    v = app.p.get_attribute(f'[data-sim="{key}"]', "data-val")
    return v if key.endswith("st-before") or key.endswith("st-after") else (None if v == "" else float(v))


def fwd(c):
    """Daily budget from here on, as the simulator shows it: free money over the days left."""
    return c["avail"] / c["days"] if c["avail"] > 0 else 0


def real_run_days(app):
    return app.p.evaluate("__kis.compute().runDays")


def snapshot(app):
    return app.p.evaluate("""async()=>{
      const idb=await new Promise(r=>{const q=indexedDB.open('kis',1);q.onsuccess=()=>{const g=q.result.transaction('kv').objectStore('kv').get('state');g.onsuccess=()=>r(g.result||null)}});
      return {ls:localStorage.getItem('kis.v1'),idb,mem:JSON.stringify([__kis.S,__kis.M])}}""")


# ---------- the simulation never changes real data ----------

def test_simulation_does_not_touch_storage_or_state(app):
    app.open(); app.onboard(); app.add("30", "food")
    app.p.wait_for_timeout(600)  # let the debounced IndexedDB copy settle
    before = snapshot(app)
    app.p.evaluate("()=>{window.__real=[__kis.S,__kis.M]}")  # the real objects, to prove they stay the live ones
    app.p.evaluate("""()=>{window.__sets=0;const o=Storage.prototype.setItem;
      Storage.prototype.setItem=function(){window.__sets++;return o.apply(this,arguments)}}""")
    whatif(app, "1200", "shop", installments=6)
    app.p.click("#simback"); app.p.wait_for_selector("#whatif"); app.p.click("#whatif")
    app.p.wait_for_selector("#simfig")
    app.p.click("#simno"); app.p.wait_for_selector("#sheet", state="hidden")
    for _ in range(20):  # the engine call itself, repeatedly
        app.p.evaluate("""()=>__kis.whatIf([null,{id:'x',d:'2026-11-26',amt:500,t:'exp',m:'card',cat:'shop',note:'',n:3,c:Date.now(),src:''}])""")
    app.p.wait_for_timeout(600)
    after = snapshot(app)
    assert app.p.evaluate("window.__sets") == 0
    assert app.p.evaluate("__kis.S===__real[0]&&__kis.M===__real[1]")
    assert after == before


def test_simulation_survives_an_engine_error(app):
    app.open(); app.onboard()
    before = app.state()
    with pytest.raises(Exception):  # a broken variant must not leave the copy installed
        app.p.evaluate("()=>__kis.whatIf([{id:'x',d:null,amt:1,t:'exp',m:'card',n:1,cat:'x',src:''}])")
    assert app.state() == before


# ---------- numbers equal a real add of the same expense ----------

CASES = [("30", "food", "card", 1), ("20", "bus", "now", 1), ("1200", "shop", "card", 6),
         ("5000", "shop", "card", 12), ("900", "shop", "now", 1), ("1200", "shop", "card", 1)]


@pytest.mark.parametrize("amount,cat,method,n", CASES)
def test_numbers_match_a_real_add(app, amount, cat, method, n):
    app.open(); app.onboard()
    b = app.calc()
    b_run = real_run_days(app)
    whatif(app, amount, cat, method, n)
    sim = {k: val(app, k) for k in ("safe-before", "safe-after", "daily-before", "daily-after", "run-before", "run-after")}
    sim_st = (val(app, "st-before"), val(app, "st-after"))
    app.p.click("#simbuy"); app.p.wait_for_selector("#sheet", state="hidden")
    a = app.calc()
    assert sim["safe-before"] == pytest.approx(b["safe"]) and sim["daily-before"] == pytest.approx(fwd(b))
    assert sim["run-before"] == b_run and sim_st[0] == b["st"]
    assert sim["safe-after"] == pytest.approx(a["safe"]) and sim["daily-after"] == pytest.approx(fwd(a))
    assert sim["run-after"] == real_run_days(app) and sim_st[1] == a["st"]


def test_installment_rows_match_real_adds(app):
    """Each row of the 1/3/6/12 comparison equals really adding that purchase on a card."""
    app.open(); app.onboard()
    whatif(app, "1200", "shop", method="now")
    rows = {n: (val(app, f"n{n}-safe"), val(app, f"n{n}-daily"), val(app, f"n{n}-run")) for n in (1, 3, 6, 12)}
    app.p.click("#simno"); app.p.wait_for_selector("#sheet", state="hidden")
    for n in (3, 12):
        app.add("1200", "shop", installments=n)
        c = app.calc()
        assert rows[n][0] == pytest.approx(c["safe"]) and rows[n][1] == pytest.approx(fwd(c))
        assert rows[n][2] == real_run_days(app)
        app.p.click("#toastB")  # undo, back to the clean state for the next row


# ---------- installments hurt the daily budget less ----------

def test_installments_reduce_daily_budget_less_than_one_payment(app):
    app.open(); app.onboard()
    whatif(app, "1200", "shop", installments=1)
    d = [val(app, f"n{n}-daily") for n in (1, 3, 6, 12)]
    assert d == [0, 25, 35, 40]  # 1200 in one go eats everything; (900-400)/20, (900-200)/20, (900-100)/20


def test_installments_leave_more_to_spend_today(app):
    app.open(); app.onboard()
    whatif(app, "30", "food", installments=1)
    s = [val(app, f"n{n}-safe") for n in (1, 3, 6, 12)]
    assert s == [15, 35, 40, 42.5] and s == sorted(s) and len(set(s)) == 4


def test_six_payments_beat_one_for_a_smaller_purchase_too(app):
    app.open(); app.onboard()
    whatif(app, "300", "shop", installments=1)
    one, six = val(app, "n1-daily"), val(app, "n6-daily")
    assert one == pytest.approx(30) and six > one  # (900-300)/20 vs (900-50)/20
    app.p.click("#simback")
    app.p.click('[data-n="1"]'); app.p.click("#whatif"); app.p.wait_for_selector("#simfig")
    assert val(app, "daily-after") == pytest.approx(37.5)  # 2 payments: first 150 reserved, (900-150)/20


# ---------- the result screen ----------

def test_result_screen_content_for_a_normal_purchase(app):
    app.open(); app.onboard()
    whatif(app, "300", "shop")
    text = app.p.inner_text("#simline")
    assert "הקנייה מורידה את התקציב היומי" in text and "₪45" in text and "₪30" in text and "עד ה-16 בדצמבר" in text
    assert val(app, "safe-before") == 45 and val(app, "safe-after") == 0  # 300 spent today uses up today's 45
    assert val(app, "daily-before") == 45 and val(app, "daily-after") == pytest.approx(30)
    assert val(app, "st-before") == "ok" and val(app, "st-after") == "warn"  # today's allowance is gone: yellow
    assert app.p.locator('[data-sim="st-after"] .pill').count() == 1
    assert "ירוק" in app.p.inner_text('[data-sim="st-before"]') and "צהוב" in app.p.inner_text('[data-sim="st-after"]')
    # chart: dashed 'before' line and a solid 'after' line on the same axes
    assert app.p.locator("#simfig svg path[stroke-dasharray]").count() == 1
    assert app.p.locator("#simfig svg path[stroke-width='2.2']").count() == 1
    assert app.p.locator('.crow[data-n]').count() == 4


def test_sentence_when_purchase_exceeds_free_money(app):
    app.open(); app.onboard()
    whatif(app, "1200", "shop", installments=1)
    text = app.p.inner_text("#simline")
    assert "גדולה מהכסף הפנוי" in text and "₪300" in text
    assert val(app, "safe-after") == 0
    assert "אדום" in app.p.inner_text('[data-sim="st-after"]')


def test_sentence_when_purchase_is_negligible(app):
    app.open(); app.onboard()
    whatif(app, "1", "food")
    assert "כמעט לא משנה" in app.p.inner_text("#simline")


def test_money_runs_out_earlier_with_spending_history(app):
    app.open(); app.onboard()
    # three days of history so the engine uses the real spending rate (no UI path to back-date quickly)
    app.p.evaluate("""()=>{const m=__kis.M['2026-11']=__kis.M['2026-11']||[];
      for(const d of ['2026-11-20','2026-11-22','2026-11-24'])m.push({id:'h'+d,d,amt:40,t:'exp',m:'now',cat:'food',note:'',n:1,c:1,src:''})}""")
    whatif(app, "300", "shop", method="now")
    text = app.p.inner_text("#simline")
    before, after = val(app, "run-before"), val(app, "run-after")
    assert before is not None and after is not None and after < before
    assert "מוקדם יותר" in text and f"{int(before - after)}" in app.p.inner_text('[data-sim="run-after"]')


# ---------- actions ----------

def test_buy_saves_a_real_expense_with_undo(app):
    app.open(); app.onboard()
    n0 = len(app.p.evaluate("Object.values(__kis.M).flat()"))
    whatif(app, "300", "shop")
    app.p.click("#simbuy"); app.p.wait_for_selector("#sheet", state="hidden")
    txs = app.p.evaluate("Object.values(__kis.M).flat()")
    assert len(txs) == n0 + 1 and txs[-1]["amt"] == 300 and txs[-1]["cat"] == "shop" and txs[-1]["m"] == "card"
    app.p.click("#toastB")
    assert len(app.p.evaluate("Object.values(__kis.M).flat()")) == n0


def test_not_now_saves_nothing(app):
    app.open(); app.onboard()
    before = app.state()
    whatif(app, "300", "shop")
    app.p.click("#simno"); app.p.wait_for_selector("#sheet", state="hidden")
    assert app.state() == before


def test_back_to_editing_keeps_what_was_typed(app):
    app.open(); app.onboard()
    whatif(app, "250", "bus", method="now")
    app.p.click("#simback"); app.p.wait_for_selector("#save")
    assert "250" in app.p.text_content("#ab")
    assert app.p.get_attribute('[data-m="now"]', "aria-pressed") == "true"
    assert app.p.get_attribute('[data-cat="bus"]', "aria-pressed") == "true"


def test_whatif_needs_an_amount_and_only_shows_for_new_expenses(app):
    app.open(); app.onboard()
    app.p.click("#fab"); app.p.click("#whatif")
    assert app.p.text_content("#aerr") == "מקלידים סכום קודם"
    assert app.p.locator("#simfig").count() == 0
    app.p.click('[data-ty="inc"]')
    assert app.p.locator("#whatif").count() == 0  # not for income
    app.p.click("#sheet [data-close]"); app.p.wait_for_selector("#sheet", state="hidden")
    app.add("30"); app.tab("list"); app.p.click("[data-tx]"); app.p.wait_for_selector("#save")
    assert app.p.locator("#whatif").count() == 0  # not when editing


def test_save_button_still_works_next_to_whatif(app):
    app.open(); app.onboard()
    app.add("30", "food")
    assert app.calc()["safe"] == 15


def test_whatif_controls_are_at_least_44px(app):
    app.open(); app.onboard()
    fill(app, "300", "shop")
    h = lambda: app.p.evaluate("[...document.querySelectorAll('#sheet #whatif,#sheet #save')].map(b=>b.getBoundingClientRect().height)")
    assert min(h()) >= 44
    app.p.click("#whatif"); app.p.wait_for_selector("#simfig")
    heights = app.p.evaluate("[...document.querySelectorAll('#sheet button')].map(b=>b.getBoundingClientRect().height)")
    assert len(heights) == 4 and min(heights) >= 44  # close, back, buy, not now
