"""The Yard Lear: exact production, excluding Lear: The Gala.

All 39 public instances were matched to the official November-January
calendar on 29 October 2026. Read public web data only; no theatre login.
Empty price bands require an explicit ordinary-seat status, never zero.
"""
import re
from datetime import datetime
from urllib.parse import urlencode

import monitor

SHOW = "https://www.theyardtheatre.co.uk/events/lear"
API = "https://system.spektrix.com/theyard/api/v3"
EVENT_ID = "83436AJGHHQJMSMGNGCSMSMBTGNPCVLHT"
END = datetime(2027, 1, 2, 19, 30, tzinfo=monitor.LONDON)
STATE_PATH = "lear-state.json"
NAME = "The Yard Theatre《Lear》Ian McKellen"


def select_event(events):
    if not isinstance(events, list):
        raise monitor.MonitorError("Invalid official Yard event list")
    matches = [event for event in events if event.get("id") == EVENT_ID and
               event.get("name") == "Lear" and event.get("webEventId") == "LEAR" and
               event.get("webUrl") == SHOW]
    if len(matches) != 1:
        raise monitor.MonitorError("Exact Yard Lear production missing or ambiguous; Gala excluded")


def parse_inventory(instances, inventory, now):
    rows = inventory.get("data") if isinstance(inventory, dict) else None
    if not isinstance(instances, list) or not instances or not isinstance(rows, list) or not rows:
        raise monitor.MonitorError("Official Lear performance or inventory list is empty")
    by_id = {}
    for row in rows:
        identifier = row.get("eventInstanceId")
        if not isinstance(identifier, str) or identifier in by_id:
            raise monitor.MonitorError("Duplicate or invalid Lear inventory identity")
        by_id[identifier] = row
    candidates, fallback, seen, total = [], [], set(), 0
    for item in instances:
        if item.get("event", {}).get("id") != EVENT_ID or item.get("planId") != "6010ATSSNGRDNNRDDDNRQJKDQBNQMMLNT":
            raise monitor.MonitorError("Not the requested Yard Lear production")
        start = monitor.date(item.get("start")).astimezone(monitor.LONDON)
        identifier = item.get("id", "")
        if not re.fullmatch(r"\d+[A-Z]+", identifier) or identifier in seen:
            raise monitor.MonitorError("Duplicate or invalid Lear performance identity")
        seen.add(identifier)
        if not now < start <= END or item.get("cancelled") is True:
            continue
        if type(item.get("isOnSale")) is not bool:
            raise monitor.MonitorError("Missing Lear public sale status")
        total += 1
        if (not item["isOnSale"] or monitor.restricted(str(item)) or
                not monitor.date(item.get("startSellingAtWebUtc")) <= now < monitor.date(item.get("stopSellingAtWebUtc"))):
            continue
        row = by_id.get(identifier)
        if row is None or monitor.date(row.get("start")) != start:
            raise monitor.MonitorError("Missing or mismatched Lear inventory date")
        bands = row.get("availability")
        if not isinstance(bands, list):
            raise monitor.MonitorError("Missing Lear price-band inventory")
        url = "https://tickets.theyardtheatre.co.uk/theyard/website/ChooseSeats.aspx?" + urlencode({
            "EventInstanceId": re.match(r"\d+", identifier)[0], "resize": "true"})
        candidate = {"instance_id": identifier, "key": start.isoformat() + "|" + url,
                     "when": start.strftime("%Y-%m-%d %H:%M"), "url": url}
        if not bands:
            fallback.append(candidate)
            continue
        available = 0
        for band in bands:
            if band.get("status") not in {"Available", "Unavailable"}:
                raise monitor.MonitorError("Unexpected Lear inventory status")
            seats = monitor.count(band.get("count"))
            if band["status"] == "Available":
                available += seats
        if available:
            candidates.append(candidate)
    if not total:
        raise monitor.MonitorError("No remaining Lear performances returned")
    return {"total": total, "candidates": candidates, "fallback": fallback}


def read_status(candidate):
    status = monitor.request_json(API + "/instances/" + candidate["instance_id"] + "/status?includeChildPlans=true")
    if not isinstance(status, dict) or status.get("name") != "The Yard Theatre 2026":
        raise monitor.MonitorError("Lear status does not identify The Yard Theatre 2026")
    return monitor.confirm_public_seats(candidate, status)


def observe(now, on_candidates=None):
    select_event(monitor.request_json(API + "/events?" + urlencode({"name": "Lear"})))
    query = "?" + urlencode({"start_from": now.astimezone(monitor.LONDON).date().isoformat(), "start_to": "2027-01-03"})
    base = API + "/events/" + EVENT_ID
    result = parse_inventory(monitor.request_json(base + "/instances" + query),
                             monitor.request_json(base + "/availability" + query), now)
    candidates = list(result["candidates"])
    available = []
    # Empty bands do not prove zero stock. Require explicit instance status.
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
            "source": "official_yard_lear_spektrix_public_inventory_and_ordinary_status"}


def alert_body(items, now):
    lines = [NAME + " 普通公开余票已核实。", "",
             f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    lines += [f"\n- **{item['when']}（伦敦时间）**：核验时 {item['count']} 张普通公开票；[官方购票页]({item['url']})" for item in items]
    lines += ["", "本次实际票价未知，请在官方售票页核对；官网列示普通票£12.50–£92.50，另有£150–£300的Legend票。官网提示需自行登录后选座。余票随时可能售出，演员安排以剧院公告为准。监控不登录、不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    return monitor.run(config={"name": NAME, "prefix": "lear", "url": SHOW,
                               "end": END, "format_alert": alert_body},
                       observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
