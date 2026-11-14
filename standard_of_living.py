"""Watch Theatre Royal Haymarket's public seats up to £125, fees included."""
import re
import time
from datetime import datetime

import monitor
from virginia_woolf import SohoBrowser

NAME = "The Standard of Living"
VENUE = "Theatre Royal Haymarket"
CALENDAR = "https://ticketing.trh.co.uk/event/79347"
STATE = "standard-of-living-state.json"
END = datetime(2026, 12, 12, 19, 30, tzinfo=monitor.LONDON)
LIMIT = 12_500
BOOKING_URL = re.compile(re.escape(CALENDAR) + r"/performance/\d+/?")
PRICE = re.compile(r"£\s*(\d+)(?:\.(\d{2}))?")
RESTRICTED_SEAT = re.compile(r"restrict|obstruct|partial view|limited view|side view|wheelchair|companion|under[\s-]*(?:25|30)|keynes tickets|members? only|access only", re.I)

CALENDAR_DOM = r"""
const calendar = document.querySelector('.rdp');
return {
  url: location.href, title: document.title,
  venue: document.querySelector('header[aria-label]')?.getAttribute('aria-label') || '',
  month: calendar?.querySelector('h2')?.innerText.trim() || document.querySelector('h2')?.innerText.trim() || '',
  challenge: /quick security check|couldn.t verify your browser/i.test(document.body.innerText),
  slots: [...document.querySelectorAll('.time-slot-tile')].flatMap((el, index) => {
    const day = el.closest('.rdp-day');
    if (!day || day.classList.contains('rdp-day_outside')) return [];
    return [{index, day: el.parentElement.querySelector('span')?.textContent.trim(),
      time: el.querySelector('span')?.textContent.trim(),
      text: el.innerText, disabled: el.getAttribute('aria-disabled') === 'true'}];
  })
};
"""

SEAT_DOM = r"""
const shown = el => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
const levels = [...document.querySelectorAll('button[role="switch"][aria-description="Filter performances"]')]
  .filter(el => shown(el) && /^£/.test(el.getAttribute('aria-label') || ''))
  .map(el => ({price: el.getAttribute('aria-label').trim(),
    color: el.querySelector('[color]') ? getComputedStyle(el.querySelector('[color]')).backgroundColor : null}));
const seatElements = [...document.querySelectorAll('g[data-seat-id][role="button"]')];
const seats = seatElements.filter(el => shown(el) && el.getAttribute('aria-disabled') !== 'true'
  && el.getAttribute('tabindex') === '0' && el.getAttribute('aria-pressed') === 'false').map(el => ({
    id: el.getAttribute('data-seat-id'),
    label: el.getAttribute('aria-label') || '',
    detail: [...el.querySelectorAll('[aria-label],title')].map(note => note.getAttribute('aria-label') || note.textContent).join(' '),
    hasNotice: Boolean(el.querySelector('[aria-label="CircleInformation"]')),
    color: el.querySelector('circle') ? getComputedStyle(el.querySelector('circle')).fill : null
  }));
const text = document.body.innerText;
return {url: location.href, title: document.title, text: text.slice(0,3500), levels, seats,
  map: seatElements.length > 0,
  challenge: /quick security check|couldn.t verify your browser/i.test(text),
  soldOut: /this performance (?:is|has) sold out|there are no tickets available for this performance/i.test(text)};
"""


def pence(value):
    match = PRICE.fullmatch(value)
    if not match:
        raise monitor.MonitorError("Official ticket price is unrecognised")
    return int(match[1]) * 100 + int(match[2] or 0)


def parse_calendar(data, month, now):
    expected = datetime(2026, month, 1).strftime("%B 2026")
    if data["url"] != f"{CALENDAR}?date=2026-{month:02}" or NAME not in data["title"] or VENUE not in data["venue"] or data["month"] != expected:
        raise monitor.MonitorError(f"Unexpected Haymarket calendar: {data['title']!r} / {data['venue']!r} / {data['month']!r}")
    if not data["slots"]:
        raise monitor.MonitorError("Official Haymarket calendar was empty")
    slots = {}
    for item in data["slots"]:
        try:
            time = datetime.strptime(item["time"].upper(), "%I:%M%p").time()
            start = datetime(2026, month, int(item["day"]), time.hour, time.minute, tzinfo=monitor.LONDON)
        except (ValueError, TypeError) as exc:
            raise monitor.MonitorError("Official calendar date or time is unrecognised") from exc
        if start in slots:
            raise monitor.MonitorError("Duplicate Haymarket performance")
        if not now < start <= END:
            continue
        price = re.search(r"\bfrom\s+(" + PRICE.pattern + ")", item["text"], re.I)
        slots[start] = dict(item, start=start, price=pence(price[1]) if price else None)
    return list(slots.values())


def confirm(slot, data):
    start = slot["start"]
    date = f"{start:%A} {start.day} {start:%B %Y, %I:%M %p}"
    if not BOOKING_URL.fullmatch(data["url"]) or NAME not in data["title"] or VENUE not in data["text"] or date not in data["text"]:
        raise monitor.MonitorError("Haymarket seat map does not match the selected performance")
    if data["soldOut"] and not data["seats"]:
        return None
    if not data["map"] or not data["levels"]:
        raise monitor.MonitorError("Official Haymarket seat map could not be verified")
    prices = {}
    for level in data["levels"]:
        color, price = level["color"], pence(level["price"])
        if not color or (color in prices and prices[color] != price):
            raise monitor.MonitorError("Ambiguous price band in Haymarket seat map")
        prices[color] = price
    seats = {}
    for seat in data["seats"]:
        # The live £100 restricted seats have a notice icon but their SVG
        # labels contain only the seat number. Exclude any unclassified notice.
        if not seat["label"] or seat["hasNotice"] or RESTRICTED_SEAT.search(seat["label"] + " " + seat["detail"]):
            continue
        if seat["color"] not in prices:
            raise monitor.MonitorError("Selectable Haymarket seat has no matching price")
        price = prices[seat["color"]]
        if 0 < price <= LIMIT:
            seats[seat["id"]] = price
    if not seats:
        return None
    url = data["url"].rstrip("/")
    return {"key": start.isoformat() + "|" + url, "url": url, "when": start.strftime("%Y-%m-%d %H:%M"),
            "prices": sorted(set(seats.values())), "count": len(seats), "confirmed": True}


class HaymarketBrowser(SohoBrowser):
    def read_page(self, script, ready):
        def read():
            data = self.script(script)
            if data["challenge"]:
                raise monitor.MonitorError("Haymarket booking requires a browser security check")
            return data

        data = self.wait(read, ready, time.monotonic() + 12)
        if data is None:
            raise monitor.MonitorError("Haymarket public booking page did not load")
        return data

    def calendar(self, month):
        self.call(f"/session/{self.session}/url", "POST", {"url": f"{CALENDAR}?date=2026-{month:02}"})
        self.script("const b=document.querySelector('#CybotCookiebotDialogBodyButtonDecline'); if(b?.getClientRects().length) b.click();")
        return self.read_page(CALENDAR_DOM, lambda d: bool(d["slots"]) and NAME in d["title"])

    def booking(self, slot):
        clicked = self.script(r"""
const [index, day, time] = arguments;
const tile = document.querySelectorAll('.time-slot-tile')[index];
if (!tile || tile.parentElement.querySelector('span')?.textContent.trim() !== day
    || tile.querySelector('span')?.textContent.trim() !== time) return false;
const decline = document.querySelector('#CybotCookiebotDialogBodyButtonDecline');
if (decline?.getClientRects().length) decline.click();
tile.click();
return true;
""", slot["index"], slot["day"], slot["time"])
        if not clicked:
            raise monitor.MonitorError("The Haymarket calendar changed during inspection")
        return self.read_page(SEAT_DOM, lambda d: BOOKING_URL.fullmatch(d["url"]) and (d["soldOut"] or (d["map"] and d["levels"])))


def observe(now, on_candidates=None):
    total, available, errors = 0, [], []
    now = now.astimezone(monitor.LONDON)
    with HaymarketBrowser() as browser:
        for month in range(now.month, END.month + 1):
            try:
                slots = parse_calendar(browser.calendar(month), month, now)
            except (monitor.MonitorError, OSError) as exc:
                errors.append(str(exc))
                break
            total += len(slots)
            candidates = [slot for slot in slots if not slot["disabled"] and (slot["price"] is None or slot["price"] <= LIMIT)]
            for index, slot in enumerate(candidates):
                try:
                    if index:
                        current = parse_calendar(browser.calendar(month), month, now)
                        slot = next((item for item in current if item["start"] == slot["start"]), None)
                        if slot is None or slot["disabled"]:
                            raise monitor.MonitorError("Official calendar changed during ticket verification")
                    match = confirm(slot, browser.booking(slot))
                    if match:
                        available.append(match)
                except (monitor.MonitorError, OSError) as exc:
                    errors.append(str(exc))
    if not total and not errors:
        errors.append("No future Haymarket performances were verified")
    if on_candidates is not None:
        on_candidates(available, confirmed_keys={item["key"] for item in available}, preserve_unseen=bool(errors))
    return {"total": total, "available": available, "errors": errors, "source": "official_haymarket_calendar_and_price_matched_seats"}


def alert_body(items, now):
    lines = [f"{VENUE} 官方选座图发现 £125 及以下、未标注视线受限的公开余票（含订票费和剧院修缮费）。",
             f"核验时间 {now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M}（伦敦时间）。"]
    for item in items:
        prices = "、".join(f"£{price // 100}.{price % 100:02}" for price in item["prices"])
        lines.append(f"\n- **{item['when']}** · {item['count']} 张 · {prices} · [官方选座页]({item['url']})")
    return "\n".join(lines + ["", "余票随时可能售出。"])


if __name__ == "__main__":
    monitor.run(config={"name": NAME, "prefix": "standard-of-living", "url": CALENDAR, "end": END,
                        "format_alert": alert_body}, observer=observe, github=lambda: monitor.GitHub(STATE))
