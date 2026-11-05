"""RSC As You Like It: 6–7 November only; 5 November excluded by user.

Fresh ordinary cloud Chrome reads the official event list and, for a positive
signal, opens its supplied booking link and section controls. Never click a
seat, log in, import cookies, solve verification, or add anything to a cart.
"""
import json
import os
import re
import time
from datetime import datetime

import monitor
from golden_boy import Browser

SHOW = "https://www.rsc.org.uk/as-you-like-it/"
CALENDAR = "https://secure.rsc.org.uk/events/as-you-like-it?startdate=2026-09-26&enddate=2026-11-07"
NAME = "As You Like It（RSC）"
STATE_PATH = "rsc-as-you-like-it-state.json"
END = datetime(2026, 11, 7, 19, 30, tzinfo=monitor.LONDON)
# Matched to the official visible production 62239 on 5 November.
SCOPE = {"62530": "2026-11-06T19:30:00+00:00",
         "62573": "2026-11-07T13:30:00+00:00",
         "62531": "2026-11-07T19:30:00+00:00"}

CALENDAR_DOM = r"""
const root = document.querySelector('[data-tn-prod-season-no="62239"]');
const text = e => (e?.textContent||'').replace(/\s+/g,' ').trim();
return {title:text(root?.querySelector('h4')),
 description:text(root?.querySelector('.tn-prod-list-item__property--description')),
 rows:Array.from(root?.querySelectorAll('[data-tn-performance-no]')||[]).map(e=>({
 id:e.getAttribute('data-tn-performance-no'),date:text(e.querySelector('.tn-prod-list-item__perf-date')),
 time:text(e.querySelector('.tn-prod-list-item__perf-time')),
 status:text(e.querySelector('.tn-prod-list-item__perf-property--action')),
 note:text(e.querySelector('.tn-prod-list-item__perf-property--title')),url:e.querySelector('a')?.href}))};
"""

BOOKING_DOM = r"""
const visible = e => e.getClientRects().length > 0;
const text = e => (e?.textContent||'').replace(/\s+/g,' ').trim();
const sections=Array.from(document.querySelectorAll('#tn-syos-screen-list button'));
return {url:location.origin+location.pathname,
 summary:text(document.querySelector('#tn-prod-season-header-summary-heading')?.parentElement),
 selected:document.querySelector('#tn-additional-events-select-desktop')?.selectedOptions?.[0]?.textContent||'',
 text:(document.body?.innerText||'').slice(0,12000),
 sections:sections.map((e,index)=>({index,label:text(e),disabled:e.disabled||e.getAttribute('aria-disabled')==='true',visible:visible(e)})).filter(e=>e.visible),
 mapLoaded:Array.from(document.querySelectorAll('[data-tn-seat-id]')).some(visible),
 seats:Array.from(document.querySelectorAll('[data-tn-seat-id]')).filter(visible).map(e=>({
 id:e.getAttribute('data-tn-seat-id'),label:e.getAttribute('aria-label')||'',
 disabled:e.getAttribute('aria-disabled')==='true',pressed:e.getAttribute('aria-pressed'),
 icon:e.querySelector('use')?.getAttribute('xlink:href')||''})),
 prices:Array.from(document.querySelectorAll('#tn-syos-legend .tn-syos-legend__description-group')).map(e=>({
 symbol:e.querySelector('svg')?.getAttribute('aria-label')||'',
 full:Array.from(e.querySelectorAll('.tn-syos-legend__zone-pricetype-list-item')).filter(p=>
 text(p.querySelector('.tn-syos-legend__zone-pricetype-label'))==='Full Price').map(p=>text(p.querySelector('.tn-syos-legend__zone-pricetype-price')))}))};
"""


def parse_calendar(data, now):
    if data.get("title", "").casefold() != "as you like it" or not all(
            word in data.get("description", "") for word in ["Jonathan Groff", "Royal Shakespeare Theatre"]):
        raise monitor.MonitorError("RSC calendar production identity was not verified")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise monitor.MonitorError("RSC calendar is empty or blocked; not evidence of sold out")
    seen, candidates, total = set(), [], 0
    for row in rows:
        identifier = row.get("id")
        if identifier in seen:
            raise monitor.MonitorError("Duplicate RSC performance")
        seen.add(identifier)
        # Exclude all 5 November tickets, even if they become available.
        if identifier not in SCOPE:
            continue
        start = datetime.strptime(row.get("date", "") + " " + row.get("time", ""),
                                  "%A %d %b %Y %I:%M%p").replace(tzinfo=monitor.LONDON)
        url = row.get("url")
        if start != monitor.date(SCOPE[identifier]) or url != "https://secure.rsc.org.uk/as-you-like-it/" + identifier:
            raise monitor.MonitorError("RSC performance date or official link does not match")
        if start <= now:
            continue
        total += 1
        status = row.get("status", "").strip().casefold()
        if status == "sold out":
            continue
        if status not in {"book tickets", "limited availability", "available"}:
            raise monitor.MonitorError("Unverified RSC sale state; not evidence of sold out")
        if monitor.restricted(row.get("note", "")):
            continue
        candidates.append({"id": identifier, "start": start.isoformat(),
                           "key": start.isoformat() + "|" + url, "url": url,
                           "when": start.strftime("%Y-%m-%d %H:%M")})
    expected = {key for key, value in SCOPE.items() if now < monitor.date(value)}
    if not expected.issubset(seen) or total != len(expected):
        raise monitor.MonitorError("Incomplete RSC remaining-performance coverage")
    return {"total": total, "candidates": candidates}


def confirm_booking(candidate, data):
    start = monitor.date(candidate["start"])
    expected = start.strftime("%A %d %b %Y ") + f"{start.hour % 12 or 12}:{start.minute:02}{'pm' if start.hour >= 12 else 'am'}"
    if (data.get("url") != candidate["url"] or "AS YOU LIKE IT" not in data.get("summary", "").upper()
            or not data.get("selected", "").startswith(expected)
            or "Royal Shakespeare Theatre" not in data.get("text", "")):
        raise monitor.MonitorError("RSC booking identity/date was not verified")
    if re.search(r"\(Sold Out\)$", data["selected"], re.I):
        return None
    prices = {}
    for price in data.get("prices", []):
        match = re.fullmatch(r"Character ([A-Z]) within a circle", price.get("symbol", ""))
        full = price.get("full", [])
        if match and len(full) == 1 and re.fullmatch(r"£\d+(?:\.\d{2})?", full[0]):
            prices[match[1].lower()] = full[0]
    seats = []
    for seat in data.get("seats", []):
        # A normal circle icon must have a Full Price entry. Exclude access,
        # companion, wheelchair, locked and selected seats; never use £18 min.
        match = re.fullmatch(r"#tn-syos-seat-map-icon-circle-([a-z])", seat.get("icon", ""))
        if (seat.get("disabled") is not False or seat.get("pressed") != "false"
                or re.search(r"wheelchair|companion|access|member|unavailable", seat.get("label", ""), re.I)
                or "wheelchair" in seat.get("icon", "")):
            continue
        if not match or match[1] not in prices or not re.match(r"^[A-Z]+\d+, £", seat.get("label", "")):
            raise monitor.MonitorError("RSC selectable seat has no verified ordinary Full Price; stock is unknown")
        seats.append({"seat": seat["label"].split(",", 1)[0], "price": prices[match[1]]})
    return dict(candidate, count=len(seats), seats=seats, confirmed=True) if seats else None


class RscBrowser(Browser):
    def execute(self, script):
        return self.call(f"/session/{self.session}/execute/sync", "POST", {"script": script, "args": []})

    def wait(self, script, ready):
        for _ in range(30):
            data = self.execute(script)
            if ready(data):
                return data
            time.sleep(1)
        self.public_failure()
        raise monitor.MonitorError("RSC ordinary cloud browser did not load verified public data; no verification bypass")

    def public_failure(self):
        data = self.execute(r"""return {title:document.title,text:(document.body?.innerText||'').slice(0,1200),
          path:location.origin+location.pathname,readyState:document.readyState,
          incapsula:Boolean(document.querySelector('script[src*="_Incapsula_Resource"],iframe[src*="_Incapsula_Resource"]')),
          frames:Array.from(document.querySelectorAll('iframe')).map(e=>({title:e.title,
            path:(()=>{try{const u=new URL(e.src);return u.origin+u.pathname;}catch{return '';}})()}))};""")
        print("RSC public page at failure:", json.dumps(data, ensure_ascii=False))
        # Read the public error frame without interacting with verification.
        frames = self.call(f"/session/{self.session}/elements", "POST",
                           {"using": "css selector", "value": "iframe"})
        if len(frames) == 1:
            try:
                self.call(f"/session/{self.session}/frame", "POST", {"id": frames[0]})
                detail = self.execute("return {title:document.title,text:(document.body?.innerText||'').slice(0,1200)};")
                print("RSC public frame at failure:", json.dumps(detail, ensure_ascii=False))
            finally:
                self.call(f"/session/{self.session}/frame", "POST", {"id": None})

    def calendar(self):
        # Follow the production's actual Book Tickets link, allowing the
        # ordinary public waiting-room redirect. No imported queue tokens.
        self.call(f"/session/{self.session}/url", "POST", {"url": SHOW})
        links = []
        for _ in range(20):
            links = self.call(f"/session/{self.session}/elements", "POST", {"using": "css selector",
                              "value": "#MainContainer_PlayHubHeader_PlayHubHeaderPlannerInfo_VenueList_TicketsLink_0"})
            if links:
                break
            time.sleep(1)
        if len(links) != 1:
            self.public_failure()
            raise monitor.MonitorError("RSC official production Book Tickets link did not load")
        reject = self.call(f"/session/{self.session}/elements", "POST",
                           {"using": "css selector", "value": "#onetrust-reject-all-handler"})
        if reject:
            element = reject[0]["element-6066-11e4-a52e-4f735466cecf"]
            if self.call(f"/session/{self.session}/element/{element}/displayed"):
                self.call(f"/session/{self.session}/element/{element}/click", "POST", {})
        element = links[0]["element-6066-11e4-a52e-4f735466cecf"]
        self.call(f"/session/{self.session}/element/{element}/click", "POST", {})
        return self.wait(CALENDAR_DOM, lambda d: bool(d.get("rows")))

    def booking_data(self):
        return self.wait(BOOKING_DOM, lambda d: bool(d.get("sections") or d.get("mapLoaded") or
                         re.search(r"\(Sold Out\)$", d.get("selected", ""), re.I)))

    def confirm(self, candidate):
        self.call(f"/session/{self.session}/url", "POST", {"url": candidate["url"]})
        data = self.booking_data()
        found = confirm_booking(candidate, data)
        if found or re.search(r"\(Sold Out\)$", data.get("selected", ""), re.I):
            return found
        sections = data.get("sections", [])
        if not sections:
            raise monitor.MonitorError("RSC seat sections did not load")
        for section in sections:
            if section["disabled"]:
                continue
            # Only section buttons are addressed; no seat/cart/promo controls.
            elements = self.call(f"/session/{self.session}/elements", "POST",
                                 {"using": "css selector", "value": "#tn-syos-screen-list button"})
            element = elements[section["index"]]["element-6066-11e4-a52e-4f735466cecf"]
            self.call(f"/session/{self.session}/element/{element}/click", "POST", {})
            data = self.wait(BOOKING_DOM, lambda d: bool(d.get("mapLoaded")))
            found = confirm_booking(candidate, data)
            if found:
                return found
            buttons = self.call(f"/session/{self.session}/elements", "POST",
                                {"using": "css selector", "value": "button.tn-syos-btn-view-screens"})
            if len(buttons) != 1:
                raise monitor.MonitorError("RSC change-section control is ambiguous")
            element = buttons[0]["element-6066-11e4-a52e-4f735466cecf"]
            self.call(f"/session/{self.session}/element/{element}/click", "POST", {})
            self.wait(BOOKING_DOM, lambda d: bool(d.get("sections")))
        return None


def observe(now, on_candidates=None):
    with RscBrowser() as browser:
        result = parse_calendar(browser.calendar(), now)
        if on_candidates is not None:
            on_candidates(result["candidates"])
        available = []
        for candidate in result["candidates"]:
            found = browser.confirm(candidate)
            if found:
                available.append(found)
    return {"total": result["total"], "available": available,
            "source": "official_rsc_public_calendar_and_selectable_full_price_seats_nov6_7_only"}


def alert_body(items, now):
    lines = [NAME + " 已核实普通公开可选座位。", "Royal Shakespeare Theatre，Stratford-upon-Avon。",
             f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    for item in items:
        seats = "；".join(s["seat"] + " " + s["price"] for s in item["seats"])
        lines.append(f"\n- **{item['when']}（伦敦时间）**：至少 {item['count']} 张；{seats}。[官方购票页]({item['url']})")
    lines += ["", "仅监控11月6日、7日尚未开演的场次，已排除11月5日。另有每单£3.50手续费。余票随时可能售出。监控不选座、不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    return monitor.run(config={"name": NAME, "prefix": "rsc-as-you-like-it", "url": SHOW,
                               "end": END, "format_alert": alert_body}, observer=observe,
                       github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    if os.environ.get("RSC_DIAGNOSTIC") == "true":
        result = observe(datetime.now(monitor.LONDON))
        print(json.dumps(result, ensure_ascii=False))
    elif os.environ.get("RSC_ACTIVE") == "true":
        run()
    else:
        print("RSC is not active: ordinary cloud booking reads failed. Manual diagnostic only; no checks or alerts.")
