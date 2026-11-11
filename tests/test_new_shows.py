import copy
import json
import unittest
from unittest.mock import patch

import monitor
import an_oak_tree as oak
import virginia_woolf as woolf
import jcs_on_stage as jcs


class OakTests(unittest.TestCase):
    def test_actual_target_sold_out(self):
        self.assertEqual(oak.parse_source(EVENTS, INSTANCES, INVENTORY, NOW), [])

    def test_empty_list_is_unknown(self):
        for events, instances, inventory in [(EVENTS, [], INVENTORY), (EVENTS, INSTANCES, {"data": []}), ([], INSTANCES, INVENTORY)]:
            with self.assertRaises(monitor.MonitorError):
                oak.parse_source(events, instances, inventory, NOW)

    def test_wrong_date_or_production_is_rejected(self):
        for field, value in [("start", "2026-11-14T15:00:00"), ("id", "240701NOTREQUESTED")]:
            items = copy.deepcopy(INSTANCES)
            items[0][field] = value
            with self.assertRaises(monitor.MonitorError):
                oak.parse_source(EVENTS, items, INVENTORY, NOW)

    def test_positive_stock_for_exact_date_only(self):
        stock = copy.deepcopy(INVENTORY)
        stock["data"][0]["availability"][0]["count"] = 1
        candidates = oak.parse_source(EVENTS, INSTANCES, stock, NOW)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["url"], oak.BOOKING)
        self.assertEqual(candidates[0]["when"], "2026-11-15 15:00")

    def test_wheelchair_or_eligibility_stock_is_not_public_confirmation(self):
        candidate = {"when": "2026-11-15 15:00", "url": oak.BOOKING}
        self.assertIsNone(monitor.confirm_public_seats(candidate, {"available": 0, "capacity": 307, "wheelchairAvailable": 1, "specialAvailable": 2}))


WOOLF_NOW = monitor.date("2026-11-11T12:27:00Z")
MATINEE = "Select event Who's Afraid Of Virginia Woolf? on 2026-11-11T13:30:00"
EVENING = "Select event Who's Afraid Of Virginia Woolf? on 2026-11-11T19:00:00"
DECEMBER = "Select event Who's Afraid Of Virginia Woolf? on 2026-12-19T19:00:00"
NOV_DAY = "Open events list for the 21st of November 2026. 2 events. Availability Low Low"
NOV_EARLIEST = "Open events list for the 20th of November 2026. 1 event. Availability Low"
NOV_EXCLUDED = "Open events list for the 19th of November 2026. 1 event. Availability Low"
NOV_MATINEE = MATINEE.replace("11-11T", "11-21T")
NOV_EVENING = EVENING.replace("11-11T", "11-21T")
DEC_DAY = "Open events list for the 19th of December 2026. 1 event. Availability Low"


class WoolfTests(unittest.TestCase):
    def booking(self, event=MATINEE, performance=2020528, **data):
        return {
            "url": woolf.SERIES + "/whos-afraid-of-virginia-woolf-" + str(performance),
            "heading": "Who’s Afraid of Virginia Woolf?",
            "selected": event, "soldOut": False, "prices": [], "seats": [], **data,
        }

    def test_low_badges_do_not_gate_individual_future_checks(self):
        days = woolf.calendar_days([NOV_DAY], "November 2026", WOOLF_NOW)
        day, (_, count) = next(iter(days.items()))
        result = woolf.day_events([NOV_MATINEE, NOV_EVENING], day, count, WOOLF_NOW)
        self.assertEqual([label for _, label in result], [NOV_MATINEE, NOV_EVENING])
        later = monitor.date("2026-11-21T14:00:00Z")
        self.assertEqual([label for _, label in woolf.day_events([NOV_MATINEE, NOV_EVENING], day, count, later)], [NOV_EVENING])
        for labels in [[NOV_MATINEE], [NOV_MATINEE] * 2, [NOV_MATINEE, DECEMBER]]:
            with self.subTest(labels=labels), self.assertRaises(monitor.MonitorError):
                woolf.day_events(labels, day, count, WOOLF_NOW)

    def test_november_twentieth_is_included_and_earlier_days_are_excluded(self):
        days = woolf.calendar_days([NOV_EXCLUDED, NOV_EARLIEST], "November 2026", WOOLF_NOW)
        self.assertEqual([day.isoformat() for day in days], ["2026-11-20"])
        self.assertEqual(next(iter(days.values())), (NOV_EARLIEST, 1))

    def test_live_price_levels_and_three_svg_seats(self):
        start = monitor.date("2026-11-11T13:30:00")
        data = self.booking(prices=["£95.00", "£75.00"], seats=[
            {"id": "Stalls-C-5", "price": "£95.00"},
            {"id": "Stalls-C-6", "price": "£95.00"},
            {"id": "Stalls-F-25", "price": "£75.00"},
        ])
        confirmed, early = woolf.classify_booking(start, MATINEE, data)
        self.assertEqual(confirmed["minimum_count"], 3)
        self.assertEqual(confirmed["prices"], ["£75.00", "£95.00"])
        self.assertIsNone(early)

    def test_sold_out_prices_only_and_unknown_remain_distinct(self):
        start = monitor.date("2026-11-11T13:30:00")
        self.assertEqual(woolf.classify_booking(start, MATINEE, self.booking(soldOut=True)), (None, None))
        confirmed, early = woolf.classify_booking(start, MATINEE, self.booking(prices=["£75.00"]))
        self.assertIsNone(confirmed)
        self.assertEqual(early["url"], self.booking()["url"])
        for data in [None, self.booking(), self.booking(selected=EVENING), self.booking(url=self.booking()["url"] + "?promo=WAC")]:
            with self.assertRaises(monitor.MonitorError):
                woolf.classify_booking(start, MATINEE, data)

    def test_scans_both_months_and_preserves_confirmed_stock_on_partial_failure(self):
        notices = []
        with patch.object(woolf, "SohoBrowser") as browser:
            session = browser.return_value.__enter__.return_value
            session.month.side_effect = [[NOV_EXCLUDED, NOV_DAY], [DEC_DAY]]
            session.events.side_effect = [[NOV_MATINEE, NOV_EVENING], [DECEMBER]]
            session.read.side_effect = [
                self.booking(event=NOV_MATINEE, prices=["£75.00"], seats=[{"id": "Stalls-F-25", "price": "£75.00"}]),
                self.booking(event=NOV_EVENING, performance=2020484, prices=["£125.00"]),
                self.booking(event=DECEMBER, performance=2020517, soldOut=True),
            ]
            result = woolf.observe(WOOLF_NOW, on_candidates=lambda items, **options: notices.append((items, options)))
            self.assertEqual([call.args[0] for call in session.events.call_args_list], [NOV_DAY, DEC_DAY])
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["available"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual([x["when"] for x in notices[0][0]], ["2026-11-21 19:00", "2026-11-21 13:30"])
        self.assertTrue(notices[0][1]["preserve_unseen"])
        self.assertEqual(notices[0][1]["confirmed_keys"], {result["available"][0]["key"]})

    def test_empty_calendar_is_a_failure_before_final_performance(self):
        with patch.object(woolf, "SohoBrowser") as browser:
            browser.return_value.__enter__.return_value.month.side_effect = [[], []]
            self.assertTrue(woolf.observe(WOOLF_NOW)["errors"])
            self.assertEqual(woolf.observe(woolf.LAST_START)["total"], 0)

    def test_month_heading_can_change_before_performance_days_refresh(self):
        snapshot = {"heading": "Who’s Afraid of Virginia Woolf?", "month": "December 2026", "days": [NOV_DAY]}
        self.assertFalse(woolf.month_ready(snapshot, "December 2026"))
        snapshot["days"] = []
        self.assertFalse(woolf.month_ready(snapshot, "December 2026"))
        snapshot["days"] = [DEC_DAY]
        self.assertTrue(woolf.month_ready(snapshot, "December 2026"))


class JCSTests(unittest.TestCase):
    def slot(self):
        data = {"title": "Choose your performance - Jesus Christ Superstar | LW Theatres", "text": "Theatre Royal Drury Lane", "month": "October 2026", "slots": [{"day": "27", "time": "7:30pm", "index": 0, "text": "7:30pm from £25.00", "disabled": False}]}
        return jcs.parse_calendar(data, NOW)[0]

    def data(self):
        return {"url": "https://ticketing.lwtheatres.co.uk/event/74991/performance/1126131", "title": "Select your tickets - Jesus Christ Superstar | LW Theatres", "pageText": "Theatre Royal Drury Lane Tuesday 27 October 2026, 07:30 PM", "heading": jcs.AREA, "text": jcs.AREA + "\nAdd tickets to your basket\nNo tickets available\nThere are no tickets available for this performance\nUpdate Basket", "selects": [], "buttons": []}

    def test_actual_regular_25_pound_seats_with_stage_sold_out_do_not_alert(self):
        self.assertIsNone(jcs.classify_stage(self.slot(), self.data()))

    def test_static_stage_25_heading_is_not_quantity_evidence(self):
        data = self.data()
        data["text"] = jcs.AREA + "\nUpdate Basket"
        with self.assertRaises(monitor.MonitorError):
            jcs.classify_stage(self.slot(), data)

    def test_positive_stage_quantity_and_explicit_25_price_are_required(self):
        data = self.data()
        data.update(text=jcs.AREA + "\nAdult £25.00\nQuantity", selects=[{"options": [{"value": "0"}, {"value": "1"}]}])
        result = jcs.classify_stage(self.slot(), data)
        self.assertTrue(result["confirmed"])
        data["text"] = jcs.AREA + "\nAdult £35.00\nQuantity"
        with self.assertRaises(monitor.MonitorError):
            jcs.classify_stage(self.slot(), data)

    def test_wrong_date_venue_and_ordinary_ticket_area_are_not_accepted(self):
        for field, value in [("pageText", "Theatre Royal Drury Lane Tuesday 3 November 2026, 07:30 PM"), ("heading", "Balcony £25"), ("url", "https://ticketing.lwtheatres.co.uk/event/52584/performance/1126131")]:
            data = dict(self.data(), **{field: value})
            with self.assertRaises(monitor.MonitorError):
                jcs.classify_stage(self.slot(), data)

    def test_no_past_performance_and_no_november_calendar(self):
        data = {"title": "Jesus Christ Superstar", "text": "Theatre Royal Drury Lane", "month": "October 2026", "slots": [{"day": "20", "time": "7:30pm", "index": 0}]}
        with self.assertRaises(monitor.MonitorError):
            jcs.parse_calendar(data, NOW)
        data["month"] = "November 2026"
        with self.assertRaises(monitor.MonitorError):
            jcs.parse_calendar(data, NOW)

NOW = monitor.date("2026-10-21T22:25:00Z")
EVENTS = json.loads('[{"description": "A rare chance to see the play that shaped a theatre landscape. When it opened in 2005 Tim Crouch’s An Oak Tree changed the rules of the game, bringing into the centre of its action an actor who has neither seen nor read the play.\\r\\nIn a performance of controlled virtuosity, the playwright guides that actor through a story of loss, suggestion and the power of the mind.\\r\\nNo two shows are the same. Each ‘vividly celebrates the live, raw, communal experience of theatre’ (Financial Times). This is an audience experience like no other.", "htmlDescription": "<div id>\\r\\n\\r\\n</div>", "duration": 75, "imageUrl": "https://system.spektrix.com/theotherpalace/files/9551e4c6-9d34-46af-bfbb-b06836535f20.jpg", "isOnSale": true, "name": "An Oak Tree", "instanceDates": "7 October-15 November", "thumbnailUrl": "https://system.spektrix.com/theotherpalace/files/9551e4c6-9d34-46af-bfbb-b06836535f20-thumbnail.jpg", "webUrl": "", "webEventId": "OAK26", "id": "104401ANKRNNLHCVDTNJGJHJRJPJMRLCG", "firstInstanceDateTime": "2026-10-07T19:00:00", "firstInstanceDateTimeUtc": "2026-10-07T18:00:00Z", "lastInstanceDateTime": "2026-11-15T15:00:00", "lastInstanceDateTimeUtc": "2026-11-15T15:00:00Z", "altText": "a man\'s face partially obscured by a glass of water", "attribute_Age": "12+", "attribute_DontIncludeOnWhatsOn": false, "attribute_ThirdPartyListings": false, "attribute_Ticketsforgoodevent": false, "attribute_Venue": "Main House"}]')
INSTANCES = json.loads('[{"isOnSale": true, "planId": "4801ANHPDLLRCQPPBDBQTRQJMPNKSLKPJ", "priceList": {"id": "259401AJLBRVRQLQSBCNPSGRKJHSTSMBM"}, "event": {"id": "104401ANKRNNLHCVDTNJGJHJRJPJMRLCG"}, "start": "2026-11-15T15:00:00", "startUtc": "2026-11-15T15:00:00", "startSellingAtWeb": "2026-07-15T16:00:00", "startSellingAtWebUtc": "2026-07-15T15:00:00Z", "stopSellingAtWeb": "2026-11-15T14:30:00", "stopSellingAtWebUtc": "2026-11-15T14:30:00Z", "webInstanceId": null, "cancelled": false, "id": "240703ASRQGGVGGHTHTRHBRGMPRRGJRMH", "hasBestAvailableOverlay": false, "attribute_AudioDescribedPerformance": false, "attribute_CaptionedPerformance": false, "attribute_PostShowQAndASession": false, "attribute_PreShowDragPerformance": false, "attribute_RelaxedPerformance": false, "attribute_SignedPerformance": false, "attribute_SingalongPerformance": false, "attribute_Ticketsforgoodinstance": false, "attribute_UnderstudyPerformance": false}]')
INVENTORY = json.loads('{"data": [{"eventInstanceId": "240703ASRQGGVGGHTHTRHBRGMPRRGJRMH", "start": "2026-11-15T15:00:00", "startUtc": "2026-11-15T15:00:00Z", "capacity": 307, "startSellingForCustomer": "2026-07-15T16:00:00", "startSellingForCustomerUtc": "2026-07-15T15:00:00Z", "availability": [{"priceBand": "401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH", "status": "Available", "count": 0, "ticketTypes": []}, {"priceBand": "201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL", "status": "Available", "count": 0, "ticketTypes": []}, {"priceBand": "402AJKCLLRDNMBKMHTCGLBDHJTBPJBDNV", "status": "Available", "count": 0, "ticketTypes": []}]}]}')
