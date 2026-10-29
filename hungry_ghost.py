"""Bush Theatre's production, using its official public Spektrix service.

The official website embeds the bushtheatre client; its Studio calendar was
matched to all four remaining performances on 29 October 2026. No login/cart.
Empty availability bands are not zero: require the explicit instance status.
"""
import re
from datetime import datetime
from urllib.parse import urlencode

import monitor

SHOW = "https://www.bushtheatre.co.uk/event/the-hungry-ghost/"
API = "https://system.spektrix.com/bushtheatre/api/v3"
EVENT_ID = "121654APBHMLHQQSDQCBTGPQJKVRMKHRC"
END = datetime(2026, 10, 31, 20, tzinfo=monitor.LONDON)
STATE_PATH = "hungry-ghost-state.json"
NAME = "Bush Theatre《The Hungry Ghost》"


def select_event(events):
    if not isinstance(events, list) or len(events) != 1:
        raise monitor.MonitorError("The Hungry Ghost production missing or ambiguous")
    event = events[0]
    if (event.get("id"), event.get("name"), event.get("attribute_TicketVenue"),
            event.get("attribute_WebsiteCategorisation")) != (EVENT_ID, "The Hungry Ghost", "Studio", "Production"):
        raise monitor.MonitorError("Bush Theatre production or venue changed")


def parse_inventory(instances, inventory, now):
    rows = inventory.get("data") if isinstance(inventory, dict) else None
    if not isinstance(instances, list) or not instances or not isinstance(rows, list) or not rows:
        raise monitor.MonitorError("Official Bush performance or inventory list is empty")
    by_id = {}
    for row in rows:
        identifier = row.get("eventInstanceId")
        if not isinstance(identifier, str) or identifier in by_id:
            raise monitor.MonitorError("Duplicate or invalid Bush inventory identity")
        by_id[identifier] = row
    candidates, fallback, seen, total = [], [], set(), 0
    for item in instances:
        if item.get("event", {}).get("id") != EVENT_ID or item.get("attribute_Location") != "Studio":
            raise monitor.MonitorError("Not the requested Bush Studio production")
        start = monitor.date(item.get("start")).astimezone(monitor.LONDON)
        identifier = item.get("id", "")
        if not re.fullmatch(r"\d+[A-Z]+", identifier) or identifier in seen:
            raise monitor.MonitorError("Duplicate or invalid Bush performance identity")
        seen.add(identifier)
        if not now < start <= END or item.get("cancelled") is True:
            continue
        if type(item.get("isOnSale")) is not bool:
            raise monitor.MonitorError("Missing Bush public sale status")
        total += 1
        if (not item["isOnSale"] or monitor.restricted(str(item)) or
                not monitor.date(item.get("startSellingAtWebUtc")) <= now < monitor.date(item.get("stopSellingAtWebUtc"))):
            continue
        row = by_id.get(identifier)
        if row is None or monitor.date(row.get("start")) != start:
            raise monitor.MonitorError("Missing or mismatched Bush inventory date")
        bands = row.get("availability")
        if not isinstance(bands, list):
            raise monitor.MonitorError("Missing Bush price-band inventory")
        url = "https://tickets.bushtheatre.co.uk/bushtheatre/website/ChooseSeats.aspx?" + urlencode({
            "EventInstanceId": re.match(r"\d+", identifier)[0], "resize": "true"})
        candidate = {"instance_id": identifier, "key": start.isoformat() + "|" + url,
                     "when": start.strftime("%Y-%m-%d %H:%M"), "url": url}
        if not bands:
            fallback.append(candidate)
            continue
        available = 0
        for band in bands:
            if band.get("status") not in {"Available", "Unavailable"}:
                raise monitor.MonitorError("Unexpected Bush inventory status")
            seats = monitor.count(band.get("count"))
            if band["status"] == "Available":
                available += seats
        if available:
            candidates.append(candidate)
    if not total:
        raise monitor.MonitorError("No remaining Bush performances returned")
    return {"total": total, "candidates": candidates, "fallback": fallback}


def read_status(candidate):
    status = monitor.request_json(API + "/instances/" + candidate["instance_id"] + "/status?includeChildPlans=true")
    if not isinstance(status, dict) or status.get("name") != "STUDIO":
        raise monitor.MonitorError("Bush status does not identify the Studio")
    return monitor.confirm_public_seats(candidate, status)


def observe(now, on_candidates=None):
    select_event(monitor.request_json(API + "/events?" + urlencode({"name": "The Hungry Ghost"})))
    query = "?" + urlencode({"start_from": now.astimezone(monitor.LONDON).date().isoformat(), "start_to": "2026-11-01"})
    base = API + "/events/" + EVENT_ID
    result = parse_inventory(monitor.request_json(base + "/instances" + query),
                             monitor.request_json(base + "/availability" + query), now)
    candidates = list(result["candidates"])
    available = []
    # A real empty-band response was observed on 29 October. It is unknown
    # until this explicit status read succeeds, never silently sold out.
    for item in result["fallback"]:
        confirmed = read_status(item)
        if confirmed:
            candidates.append(item)
            available.append(confirmed)
    # Publish the complete set once, preserving deduplication for empty-band
    # fallbacks too, before checking the other positive inventory signals.
    if on_candidates is not None:
        on_candidates(candidates)
    for item in result["candidates"]:
        confirmed = read_status(item)
        if confirmed:
            available.append(confirmed)
    return {"total": result["total"], "available": available,
            "source": "official_bush_spektrix_public_inventory_and_studio_status"}


def alert_body(items, now):
    lines = [NAME + " 普通公开余票已核实。", "",
             f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    lines += [f"\n- **{item['when']}（伦敦时间）**：核验时 {item['count']} 张普通公开票；[官方购票页]({item['url']})" for item in items]
    lines += ["", "官网列示标准票价£25；本次退票的实际票价未知，请在官方售票页核对。余票随时可能售出。监控不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    return monitor.run(config={"name": NAME, "prefix": "hungry-ghost", "url": SHOW,
                               "end": END, "format_alert": alert_body},
                       observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
