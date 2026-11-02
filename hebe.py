"""Hebe at Taipei Arena: Ticket Plus public general-sale status only.

Endpoints and field meanings are from the official public site's app and
activity/order scripts. The six public and config IDs were matched using
the site's own public URL-ID conversion, then checked against the rendered
calendar on 1 November 2026. No login, queue, reservation or purchase API.
"""
from datetime import datetime
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import monitor
from golden_boy import Browser

TAIPEI = ZoneInfo("Asia/Taipei")
EVENT = "af2bd66d8fe65d78963cbb5bdc85771c"
CONFIG_EVENT = "e000001534"
SHOW = "https://ticketplus.com.tw/activity/" + EVENT
API = "https://apis.ticketplus.com.tw/config/api/v1"
TITLE = "田馥甄 要去什麼地方 2026台北小巨蛋演唱會"
END = datetime(2026, 12, 20, 18, 30, tzinfo=TAIPEI)
STATE_PATH = "hebe-state.json"
SESSIONS = {
    "c2dea0f7d2826e50da58b304bdfd47ef": ("s000002288", "2026-12-12", "18:30"),
    "85b4b97704223ce85e10b10e07575968": ("s000002289", "2026-12-13", "18:30"),
    "95f23e400e61052b487387acfb7b1a89": ("s000002290", "2026-12-15", "19:30"),
    "99c520edfa9ddb81ad598b3fad1687cc": ("s000002291", "2026-12-18", "19:30"),
    "d042e17d71c0dc8bb3e43f08ecbc50b6": ("s000002292", "2026-12-19", "18:30"),
    "5f56e43c4c02a92b92a701ad89f88784": ("s000002293", "2026-12-20", "18:30"),
}


def static(name, reader=monitor.request_json):
    return reader(API + "/getS3?" + urlencode({"path": f"event/{EVENT}/{name}.json"}))


def live(reader=monitor.request_json, **identifiers):
    return reader(API + "/get?" + urlencode({k: ",".join(v) for k, v in identifiers.items()}))


def result(payload):
    if not isinstance(payload, dict) or payload.get("errCode") != "00" or not isinstance(payload.get("result"), dict):
        raise monitor.MonitorError("Ticket Plus public status failed; not evidence of sold-out stock")
    return payload["result"]


def unique(rows, key):
    if not isinstance(rows, list) or not rows:
        raise monitor.MonitorError("Missing Ticket Plus public rows")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or row[key] in indexed:
            raise monitor.MonitorError("Invalid or duplicate Ticket Plus identity")
        indexed[row[key]] = row
    return indexed


def parse_sessions(event, sessions, payload, now):
    if (not isinstance(event, dict) or event.get("event_id") != EVENT or
            event.get("title") != TITLE or event.get("location") != "台北小巨蛋" or event.get("lotteryDeadline")):
        raise monitor.MonitorError("Wrong Hebe event: require general sale, not the expired lottery")
    metadata = unique(sessions.get("sessions") if isinstance(sessions, dict) else None, "sessionId")
    if set(metadata) != set(SESSIONS):
        raise monitor.MonitorError("Hebe calendar coverage changed: expected the six verified performances")
    data = result(payload)
    events = unique(data.get("event"), "id")
    if set(events) != {CONFIG_EVENT}:
        raise monitor.MonitorError("Wrong live Hebe event")
    statuses = unique(data.get("session"), "id")
    if set(statuses) != {s[0] for s in SESSIONS.values()}:
        raise monitor.MonitorError("Missing or unexpected Hebe live session status")
    candidates, total = [], 0
    for public_id, (identifier, day, time) in SESSIONS.items():
        meta, status = metadata[public_id], statuses[identifier]
        if (meta.get("eventId") != EVENT or meta.get("location") != "台北小巨蛋" or
                meta.get("name") != TITLE + f"（12/{int(day[-2:])}場次）" or
                meta.get("date") != f"{day} ~ {day}" or meta.get("time") != f"{time} ~ {time}" or
                meta.get("hidden") is not False or status.get("hidden") is not False or
                monitor.date(status.get("sessionStart")).astimezone(TAIPEI).date().isoformat() != day):
            raise monitor.MonitorError("Hebe performance identity, date, venue or visibility changed")
        start = datetime.fromisoformat(day + "T" + time).replace(tzinfo=TAIPEI)
        if start <= now:
            continue
        total += 1
        if status.get("status") == "soldout":
            continue
        if status.get("status") != "onsale":
            raise monitor.MonitorError("Hebe status is not an explicit sold-out or public-sale state")
        # The same onsale field displays the live booking button. Notify it
        # before the slower stock verification, including sale-window changes.
        candidates.append({"key": start.isoformat() + "|" + SHOW + "|" + identifier,
                           "url": SHOW + "#buyTicket", "when": day + " " + time,
                           "public_id": public_id, "session_id": identifier,
                           "event_status": events[CONFIG_EVENT], "session_status": status})
    if not total:
        raise monitor.MonitorError("No remaining Hebe performances before the configured end")
    return {"total": total, "candidates": candidates}


def public_window(row, now):
    if row.get("hidden") is not False or row.get("lock") not in (None, False) or row.get("isProtected") is True:
        return False
    return (row.get("status") == "onsale" and
            monitor.date(row.get("saleStart")) <= now < monitor.date(row.get("saleEnd")))


def confirm_stock(candidate, products, areas, payload, now):
    if not all(public_window(candidate[k], now) for k in ("event_status", "session_status")):
        raise monitor.MonitorError("Hebe booking signal found, but current public sale window is not verified")
    stock = result(payload)
    prods = unique(stock.get("product"), "id")
    area_stock = unique(stock.get("ticketArea"), "id")
    if set(prods) != {p["productId"] for p in products} or set(area_stock) != {p["ticketAreaId"] for p in products}:
        raise monitor.MonitorError("Hebe ordinary ticket stock is incomplete")
    confirmed = {}
    for product in products:
        row = prods[product["productId"]]
        area_id = product["ticketAreaId"]
        area = area_stock[area_id]
        if (row.get("eventId") != CONFIG_EVENT or row.get("sessionId") != candidate["session_id"] or
                row.get("ticketAreaId") != area_id or area.get("sessionId") != candidate["session_id"]):
            raise monitor.MonitorError("Hebe stock belongs to another event, performance or area")
        if row.get("disabilitiesType") != 0 or row.get("welfare") != 0 or row.get("serialKey") or row.get("coupon"):
            continue
        for source in (row, area):
            if source.get("status") not in {"onsale", "soldout", "lock", "hidden", "over", "unavailable", "pending"}:
                raise monitor.MonitorError("Unknown Hebe product or area status")
        if not public_window(row, now) or not public_window(area, now):
            continue
        if type(row.get("productLimit")) is not bool or type(area.get("ticketAreaLimit")) is not bool:
            raise monitor.MonitorError("Unknown Hebe stock-limit semantics")
        # Only explicit counts prove stock. A public onsale button, unlimited
        # ticket type, price, or static area map cannot prove a real free seat.
        counts = []
        if area["ticketAreaLimit"]:
            counts.append(monitor.count(area.get("count")))
        if row["productLimit"]:
            counts.append(monitor.count(row.get("count")))
        if not counts:
            raise monitor.MonitorError("Hebe public booking opened, but no explicit inventory count is exposed")
        available = min(counts)
        unit = monitor.count(row.get("unit"))
        if unit != 1 or not available:
            continue
        price = row.get("price")
        if type(price) is not int or price <= 0 or price != product.get("price"):
            raise monitor.MonitorError("Hebe ticket price could not be verified")
        confirmed[area_id] = {"area": areas[area_id]["name"], "price": price, "count": available}
    if not confirmed:
        return None
    return dict(candidate, count=sum(a["count"] for a in confirmed.values()), areas=list(confirmed.values()))


def read_source(now, on_candidates=None, reader=monitor.request_json):
    event, sessions = static("event", reader), static("sessions", reader)
    parsed = parse_sessions(event, sessions, live(reader=reader, eventId=[CONFIG_EVENT],
                            sessionId=[s[0] for s in SESSIONS.values()]), now)
    if on_candidates:
        on_candidates(parsed["candidates"])
    available = []
    if parsed["candidates"]:
        products = unique(static("products", reader).get("products"), "productId")
        areas = unique(static("ticketAreas", reader).get("ticketAreas"), "ticketAreaId")
        for candidate in parsed["candidates"]:
            ordinary = [p for p in products.values() if p.get("sessionId") == candidate["public_id"] and
                        p.get("name") == "全票" and p.get("hidden") is False]
            if not ordinary or any(p.get("ticketAreaId") not in areas or
                    areas[p["ticketAreaId"]].get("sessionId") != candidate["public_id"] or
                    areas[p["ticketAreaId"]].get("hidden") is not False for p in ordinary):
                raise monitor.MonitorError("Missing public ordinary Hebe ticket metadata")
            stock = live(reader=reader, productId=[p["productId"] for p in ordinary],
                         ticketAreaId=sorted({p["ticketAreaId"] for p in ordinary}))
            confirmed = confirm_stock(candidate, ordinary, areas, stock, now)
            if confirmed:
                available.append(confirmed)
    return {"total": parsed["total"], "available": available,
            "source": "official_ticketplus_hebe_general_sale_six_sessions_and_public_stock"}


class PublicBrowser(Browser):
    """Ordinary fresh Chrome, with no imported cookies or fingerprint changes.

    Navigate directly to the same public JSON URL, then read its rendered
    body. No login, CAPTCHA interaction, queue, proxy or security bypass.
    If Chrome is also refused, fail rather than trying another transport.
    """
    def read_json(self, url):
        if not url.startswith(API + "/get"):
            raise monitor.MonitorError("Unexpected Ticket Plus public source URL")
        self.call(f"/session/{self.session}/url", "POST", {"url": url})
        for _ in range(15):
            page = self.call(f"/session/{self.session}/execute/sync", "POST", {
                "script": "return {url:location.href, text:document.querySelector('pre')?.innerText || document.body?.innerText || '', ready:document.readyState};", "args": []})
            if page.get("url") != url:
                raise monitor.MonitorError("Ticket Plus public source redirected; no verified stock")
            text = page.get("text", "").strip()
            if text:
                try:
                    return json.loads(text)
                except ValueError as exc:
                    raise monitor.MonitorError("Ticket Plus ordinary cloud Chrome returned non-JSON; no verified stock. Public response: " + text[:180].replace("\n", " ")) from exc
            time.sleep(1)
        raise monitor.MonitorError("Ticket Plus public source did not load in ordinary cloud Chrome")

    def read_calendar(self):
        self.call(f"/session/{self.session}/url", "POST", {"url": SHOW})
        for _ in range(35):
            page = self.call(f"/session/{self.session}/execute/sync", "POST", {
                "script": """return {url:location.href, heading:document.querySelector('h1')?.innerText.trim() || '',
                text:document.body?.innerText.slice(0,4000) || '',
                rows:Array.from(document.querySelectorAll('#buyTicket .sesstion-item')).map(e=>({text:e.innerText,
                buttons:Array.from(e.querySelectorAll('button,a')).filter(b=>!b.disabled && b.getAttribute('aria-disabled')!=='true')
                .map(b=>({text:b.innerText.trim(),href:b.getAttribute('href')}))}))};""", "args": []})
            if len(page.get("rows", [])) == 6 and all("銷售一空" in r["text"] or r.get("buttons") for r in page["rows"]):
                return page
            if re.search(r"captcha|verify.{0,20}(human|browser)|access denied|request could not be satisfied|403 ERROR",page.get("text", ""),re.I):
                raise monitor.MonitorError("Ticket Plus official page refused ordinary cloud Chrome; no verification bypass attempted")
            time.sleep(1)
        raise monitor.MonitorError("Ticket Plus official calendar did not load six verified session rows in ordinary cloud Chrome")


def parse_rendered_calendar(page, now):
    if page.get("url") != SHOW or page.get("heading") != TITLE or len(page.get("rows", [])) != 6:
        raise monitor.MonitorError("Wrong or incomplete rendered Hebe general-sale page")
    expected = {s[1]: (p, s) for p,s in SESSIONS.items()}
    seen, candidates, total = set(), [], 0
    for row in page["rows"]:
        text = row.get("text", "")
        days = re.findall(r"2026-12-\d{2}", text)
        times = re.findall(r"\b\d{2}:\d{2}\b", text)
        if len(days) != 1 or days[0] not in expected or days[0] in seen or len(times) != 1:
            raise monitor.MonitorError("Invalid or duplicate rendered Hebe performance date")
        day = days[0];seen.add(day)
        public_id, (identifier, _, time) = expected[day]
        if TITLE + f"（12/{int(day[-2:])}場次）" not in text or "台北小巨蛋" not in text or times[0] != time:
            raise monitor.MonitorError("Rendered Hebe title, venue or performance time changed")
        start = datetime.fromisoformat(day + "T" + time).replace(tzinfo=TAIPEI)
        if start <= now:
            continue
        total += 1
        buy = [b for b in row.get("buttons", []) if b.get("text") == "立即購買"]
        if "銷售一空" in text and not buy:
            continue
        if len(buy) != 1 or "銷售一空" in text:
            raise monitor.MonitorError("Rendered Hebe status is neither explicit sold-out nor enabled booking")
        candidates.append({"key":start.isoformat()+"|"+SHOW+"|"+identifier,"when":day+" "+time,
                           "url":SHOW+"#buyTicket","public_id":public_id,"session_id":identifier})
    return {"total":total,"candidates":candidates}


def observe(now, on_candidates=None):
    try:
        return read_source(now, on_candidates)
    except HTTPError as exc:
        if exc.code != 403:
            raise
        print("Public HTTP reader received 403; checking the full official application once with ordinary fresh Chrome.")
        with PublicBrowser() as browser:
            parsed = parse_rendered_calendar(browser.read_calendar(), now)
        if on_candidates:
            on_candidates(parsed["candidates"])
        if parsed["candidates"]:
            raise monitor.MonitorError("Hebe official booking entry reopened; early alert sent, but ordinary stock remains unverified without public count access")
        return {"total":parsed["total"],"available":[],"source":"official_ticketplus_hebe_rendered_general_sale_calendar_ordinary_chrome"}


def candidate_body(name, items, now):
    lines = [name + " 的远大官方一般贩售场次重新出现购票信号，实际余票和价格待核实。",
             f"核验时间：{now.astimezone(TAIPEI):%Y-%m-%d %H:%M:%S}（台北时间，UTC+8）"]
    lines += [f"- **{p['when']}（台北时间）**：[远大官方购票页]({p['url']})" for p in items]
    lines += ["这是入口变化提醒，尚不能确认有票。演唱会采用实名制，请自行登录核对购票资格。确认普通公开库存后另行补充；余票随时可能售出。"]
    return "\n\n".join(lines)


def alert_body(items, now):
    lines = [TITLE + "：远大官方公开普通票库存已核实。",
             f"核验时间：{now.astimezone(TAIPEI):%Y-%m-%d %H:%M:%S}（台北时间，UTC+8）"]
    for p in items:
        details = "；".join(f"{a['area']} NT${a['price']:,}，库存{a['count']}张" for a in p["areas"])
        lines.append(f"**{p['when']}（台北时间）**：{details}\n[远大官方购票页]({p['url']})")
    lines += ["仅核实公开库存，未登录核对个人资格或占座。实名制购票须由本人完成，余票随时可能售出。"]
    return "\n\n".join(lines)


def run():
    return monitor.run(config={"name": TITLE, "prefix": "hebe", "url": SHOW, "end": END,
                               "format_alert": alert_body, "format_candidate": candidate_body},
                       observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    state = run()
    if state is not None and state.get("status") == "unknown":
        raise SystemExit(1)
