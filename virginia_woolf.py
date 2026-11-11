"""Check the official nLiven booking calendar and each public seat map."""
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import monitor
from golden_boy import Browser

SERIES = "https://ticketing.sohoplace.org/shop/tickets/series/SPVWF01M"
STATE_PATH = "virginia-woolf-state.json"
FIRST_DAY = date(2026, 11, 20)
END = datetime(2026, 12, 20, tzinfo=monitor.LONDON)
LAST_START = datetime(2026, 12, 19, 19, tzinfo=monitor.LONDON)
NAME = "@sohoplace《Who's Afraid of Virginia Woolf?》11月20日起"
TITLE = "whosafraidofvirginiawoolf"
DAY_LABEL = re.compile(r"Open events list for the (\d{1,2})(?:st|nd|rd|th) of ([A-Za-z]+ \d{4})\. (\d+) events?\.")
EVENT_LABEL = re.compile(r"Select event (.+) on (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)")
PRICE = re.compile(r"£\d+(?:\.\d{2})?")


def normalise_title(text):
    return re.sub(r"[^a-z]", "", text.lower())


def calendar_days(labels, month, now):
    days = {}
    first_day = max(now.date(), FIRST_DAY)
    for label in labels:
        match = DAY_LABEL.match(label)
        if not match or match[2] != month or not int(match[3]):
            raise monitor.MonitorError("Unrecognised nLiven booking calendar day")
        day = datetime.strptime(f"{match[1]} {match[2]}", "%d %B %Y").date()
        if day in days:
            raise monitor.MonitorError("Duplicate nLiven calendar day")
        if first_day <= day < END.date():
            days[day] = (label, int(match[3]))
    return days


def day_events(labels, day, expected_count, now):
    if len(labels) != expected_count or len(set(labels)) != expected_count:
        raise monitor.MonitorError(f"Incomplete booking calendar for {day}")
    events = {}
    for label in labels:
        match = EVENT_LABEL.fullmatch(label)
        if not match or normalise_title(match[1]) != TITLE:
            raise monitor.MonitorError(f"Unexpected booking calendar event on {day}")
        start = monitor.date(match[2])
        if start.date() != day or start in events:
            raise monitor.MonitorError(f"Mismatched or duplicate performance on {day}")
        events[start] = label
    return [(start, label) for start, label in sorted(events.items()) if now < start < END]


CALENDAR_DOM = r"""
const [action, target] = arguments;
const root = document.querySelector('[data-test="consumer-main-content"]');
if (!root) return null;
const daySelector = 'button[data-test^="view-series-event-calendar-day"]';
const eventSelector = 'button[data-test="view-series-event-list-event"]';
const label = el => el.getAttribute('aria-label') || '';
const buttons = selector => [...root.querySelectorAll(selector)];
const find = (selector, text) => buttons(selector).find(el => label(el) === text);
if (action === 'day') {
  const day = find(daySelector, target);
  if (!day || day.disabled) return false;
  if (day.dataset.test !== 'view-series-event-calendar-day-selected') day.click();
  return true;
}
if (action === 'event') {
  const event = find(eventSelector, target);
  if (!event || event.disabled) return false;
  if (!event.classList.contains('active')) event.click();
  return true;
}
if (action === 'next') {
  const next = root.querySelector('[data-test="view-series-event-dates-next-month"]');
  if (!next || next.disabled) return false;
  next.click();
  return true;
}
const selectedDay = root.querySelector('[data-test="view-series-event-calendar-day-selected"]');
return {
  heading: root.querySelector('h1')?.textContent || '',
  month: root.querySelector('[data-test="view-series-event-dates-select-month"]')?.innerText.trim() || '',
  days: buttons(daySelector).filter(el => !el.disabled).map(label),
  day: selectedDay ? label(selectedDay) : '',
  events: buttons(eventSelector).map(label)
};
"""


BOOKING_DOM = r"""
const root = document.querySelector('[data-test="consumer-main-content"]');
if (!root) return null;
const visible = el => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
const usable = el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true';
const restricted = /wheelchair|companion|\b(?:ada|wac)\b|members?\s+only|access\s+only|under[ -]?(?:25|30)/i;
const prices = new Map();
for (const button of root.querySelectorAll('button[data-test^="view-series-shop-by-seat-map-price-level-"]')) {
  if (!usable(button) || restricted.test(button.innerText + ' ' + (button.getAttribute('aria-label') || ''))) continue;
  const icon = button.querySelector('svg[class*="seat--pl-"]');
  const level = icon?.getAttribute('class').match(/\bseat--(pl-\d+)\b/);
  const price = button.innerText.trim();
  if (level && /^£\d+(?:\.\d{2})?$/.test(price)) prices.set(level[1], price);
}
const map = root.querySelector('[data-test="seat-map-svg"]');
const seats = [];
if (visible(map)) {
  for (const seat of map.querySelectorAll('circle[id], path[id]')) {
    if (!usable(seat) || getComputedStyle(seat).cursor !== 'pointer') continue;
    const level = seat.style.fill.match(/^var\(--color-(pl-\d+)\)$/);
    if (!level) continue;
    const description = [seat.id, seat.getAttribute('class'), seat.getAttribute('aria-label'), seat.querySelector('title')?.textContent].join(' ');
    if (restricted.test(description)) continue;
    if (prices.has(level[1])) seats.push({id: seat.id, price: prices.get(level[1])});
  }
}
const soldOut = root.querySelector('[data-test="sold-out"]');
return {
  url: location.href,
  heading: root.querySelector('h1')?.textContent || '',
  selected: root.querySelector('[data-test="view-series-event-list-event"].active')?.getAttribute('aria-label') || '',
  soldOut: Boolean(visible(soldOut) && /performance sold out/i.test(soldOut.innerText)),
  prices: [...prices.values()],
  seats
};
"""


def month_ready(data, month):
    if data["month"] != month or normalise_title(data["heading"]) != TITLE:
        return False
    # The heading changes before the day buttons are replaced after navigation.
    days = data["days"]
    return bool(days) and all((match := DAY_LABEL.match(label)) and match[2] == month for label in days)


class SohoBrowser(Browser):
    def script(self, script, *args):
        return self.call(f"/session/{self.session}/execute/sync", "POST", {"script": script, "args": args})

    def wait(self, read, ready, deadline):
        while time.monotonic() < deadline:
            data = read()
            if data and ready(data):
                return data
            time.sleep(0.2)
        return None

    def month(self, month, *, first=False):
        if first:
            self.call(f"/session/{self.session}/url", "POST", {"url": SERIES})
        elif not self.script(CALENDAR_DOM, "next", ""):
            raise monitor.MonitorError(f"Official booking calendar did not open {month}")
        data = self.wait(
            lambda: self.script(CALENDAR_DOM, "", ""),
            lambda d: month_ready(d, month),
            time.monotonic() + 12,
        )
        if data is None:
            raise monitor.MonitorError(f"Official booking calendar for {month} could not be verified")
        return data["days"]

    def events(self, day_label, expected_count):
        if not self.script(CALENDAR_DOM, "day", day_label):
            raise monitor.MonitorError("Official booking calendar day did not open")
        data = self.wait(
            lambda: self.script(CALENDAR_DOM, "", ""),
            lambda d: d["day"] == day_label and len(d["events"]) == expected_count,
            time.monotonic() + 5,
        )
        if data is None:
            raise monitor.MonitorError("Official booking calendar day did not list its performances")
        return data["events"]

    def read(self, event_label):
        if not self.script(CALENDAR_DOM, "event", event_label):
            raise monitor.MonitorError("Official performance booking did not open")
        latest = None

        def read_matching_page():
            nonlocal latest
            data = self.script(BOOKING_DOM)
            if data and data["selected"] == event_label and valid_booking_url(data["url"]):
                latest = data
            return latest

        result = self.wait(
            read_matching_page,
            lambda d: d["soldOut"] or bool(d["seats"]),
            time.monotonic() + 5,
        )
        return result or latest


def valid_booking_url(url):
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "ticketing.sohoplace.org"
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(r"/shop/tickets/series/SPVWF01M/whos-afraid-of-virginia-woolf-\d+/?", parsed.path)
    )


def classify_booking(start, event_label, data):
    if not data or not valid_booking_url(data["url"]) or normalise_title(data["heading"]) != TITLE or data["selected"] != event_label:
        raise monitor.MonitorError("Official booking page does not match the selected performance")
    url = data["url"].rstrip("/")
    item = {"key": start.isoformat() + "|" + url, "url": url, "start": start.isoformat(), "when": start.strftime("%Y-%m-%d %H:%M")}
    if data["soldOut"] and not data["seats"]:
        return None, None
    if not data["soldOut"] and data["seats"]:
        prices = {seat["price"] for seat in data["seats"]}
        if any(not PRICE.fullmatch(price) for price in prices):
            raise monitor.MonitorError("Official seat map price is unrecognised")
        count = len({seat["id"] for seat in data["seats"]})
        return dict(item, minimum_count=count, confirmed=True, prices=sorted(prices, key=lambda p: float(p[1:]))), None
    if not data["soldOut"] and data["prices"]:
        return None, item
    raise monitor.MonitorError("Official booking page did not verify ticket availability")


def observe(now, on_candidates=None):
    now = now.astimezone(monitor.LONDON)
    total, available, early, errors = 0, [], [], []
    if now >= LAST_START:
        if on_candidates is not None:
            on_candidates([])
        return {"total": 0, "available": [], "source": "official_sohoplace_nliven_seat_maps"}
    month = now.replace(day=1)
    # Leave time to save verified results before the five-minute job ends.
    deadline = time.monotonic() + 165
    with SohoBrowser() as browser:
        while month < END:
            label = month.strftime("%B %Y")
            try:
                days = calendar_days(browser.month(label, first=month.month == now.month), label, now)
                if not days and month.month != now.month:
                    raise monitor.MonitorError(f"No official performances listed for {label}")
            except (monitor.MonitorError, OSError) as exc:
                errors.append(str(exc))
                break
            for day, (day_label, expected_count) in sorted(days.items()):
                if time.monotonic() >= deadline:
                    errors.append("Booking calendar scan reached its time limit")
                    break
                try:
                    events = day_events(browser.events(day_label, expected_count), day, expected_count, now)
                except (monitor.MonitorError, OSError) as exc:
                    errors.append(f"{day}: {exc}")
                    continue
                for start, event_label in events:
                    total += 1
                    try:
                        confirmed, candidate = classify_booking(start, event_label, browser.read(event_label))
                        if confirmed:
                            available.append(confirmed)
                        if candidate:
                            early.append(candidate)
                            errors.append(f"{start:%d %b %H:%M}: public seat map could not be confirmed")
                    except (monitor.MonitorError, OSError) as exc:
                        errors.append(f"{start:%d %b %H:%M}: {exc}")
            if time.monotonic() >= deadline:
                break
            month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    if not total and not errors:
        errors.append("No future performances were verified before the final show")
    if on_candidates is not None:
        on_candidates(early + available, preserve_unseen=bool(errors), confirmed_keys={item["key"] for item in available})
    return {"total": total, "available": available, "source": "official_sohoplace_nliven_seat_maps", "errors": errors}


def alert_body(items, now):
    lines = [NAME + " 官方售票页已确认公开可选座位。", "", f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    for item in items:
        prices = "、".join(item["prices"])
        lines.append(f"\n- **{item['when']}（伦敦时间）**：{item['minimum_count']} 个公开可选座位，票价 {prices}。[官方选座页]({item['url']})")
    lines += ["", "余票随时可能售出。监控不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    return monitor.run(config={"name": NAME, "prefix": "virginia-woolf", "url": SERIES, "end": END, "format_alert": alert_body, "scope": "all_future", "empty_status": "no_future_performances"}, observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
