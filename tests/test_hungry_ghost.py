import copy
import unittest
from unittest.mock import patch
import hungry_ghost as bush
import monitor

NOW = monitor.date("2026-10-29T01:40:00Z")
STATUS = {"name":"STUDIO", "available":0, "capacity":60, "wheelchairAvailable":2, "specialAvailable":3}

class BushTests(unittest.TestCase):
    def parse(self, instances=None, inventory=None, now=NOW):
        return bush.parse_inventory(instances or INSTANCES, inventory if inventory is not None else INVENTORY, now)

    def test_official_four_future_shows_match_calendar_and_empty_band_is_unknown(self):
        result = self.parse()
        self.assertEqual(result["total"],4)
        self.assertEqual(result["candidates"],[])
        self.assertEqual(len(result["fallback"]),1)
        self.assertIn("EventInstanceId=304553",result["fallback"][0]["url"])

    def test_exact_production_and_studio_required(self):
        bush.select_event([EVENT])
        for event in [dict(EVENT,id="OTHER"),dict(EVENT,name="Hungry Ghost Programme"),dict(EVENT,attribute_TicketVenue="Main House")]:
            with self.assertRaises(monitor.MonitorError): bush.select_event([event])
        for change in [{"event":{"id":"OTHER"}},{"attribute_Location":"Main House"}]:
            rows=copy.deepcopy(INSTANCES); rows[0].update(change)
            with self.assertRaises(monitor.MonitorError): self.parse(rows)

    def test_empty_missing_duplicate_mismatched_or_invalid_counts_fail(self):
        for stock in [{}, {"data":[]}, {"data":[INVENTORY["data"][0]]}, {"data":INVENTORY["data"]*2}]:
            with self.subTest(stock=stock), self.assertRaises(monitor.MonitorError): self.parse(inventory=stock)
        for invalid in [None,-1,True,"1"]:
            stock=copy.deepcopy(INVENTORY); stock["data"][1]["availability"][0]["count"]=invalid
            with self.assertRaises(monitor.MonitorError): self.parse(inventory=stock)
        stock=copy.deepcopy(INVENTORY); stock["data"][1]["start"]="2026-10-30T19:30:00"
        with self.assertRaises(monitor.MonitorError): self.parse(inventory=stock)

    def test_past_final_evening_and_public_sale_windows(self):
        self.assertEqual(self.parse(now=monitor.date("2026-10-31T16:00:00Z"))["total"],1)
        rows=copy.deepcopy(INSTANCES); rows[0]["attribute_PerformanceType"]="Members only"
        self.assertEqual(self.parse(rows)["fallback"],[])
        rows=copy.deepcopy(INSTANCES); rows[0]["startSellingAtWebUtc"]="2026-10-30T00:00:00Z"
        self.assertEqual(self.parse(rows)["fallback"],[])

    def test_ordinary_count_only_and_correct_studio_confirmation(self):
        item=self.parse()["fallback"][0]
        with patch.object(monitor,"request_json",return_value=STATUS): self.assertIsNone(bush.read_status(item))
        with patch.object(monitor,"request_json",return_value=dict(STATUS,available=1)):
            self.assertEqual(bush.read_status(item)["count"],1)
        for status in [dict(STATUS,name="MAIN HOUSE"),dict(STATUS,available=None)]:
            with patch.object(monitor,"request_json",return_value=status), self.assertRaises(monitor.MonitorError): bush.read_status(item)

    def test_empty_bands_require_status_and_do_not_repeat_candidate_callback(self):
        for quantity in [0,1]:
            calls=[]
            def request(url):
                if "/status?" in url: return dict(STATUS,available=quantity)
                if "/availability?" in url: return INVENTORY
                if "/instances?" in url: return INSTANCES
                return [EVENT]
            with patch.object(monitor,"request_json",side_effect=request):
                result=bush.observe(NOW,on_candidates=lambda items:calls.append(list(items)))
            self.assertEqual(len(calls),1)
            self.assertEqual(len(calls[0]),quantity)
            self.assertEqual(len(result["available"]),quantity)
        with patch.object(monitor,"request_json",side_effect=[ [EVENT],INSTANCES,INVENTORY,{} ]), self.assertRaises(monitor.MonitorError): bush.observe(NOW)

    def test_positive_signal_notified_before_slow_confirmation(self):
        stock=copy.deepcopy(INVENTORY)
        stock["data"][0]["availability"]=[{"status":"Available","count":1}]
        calls=[]
        def request(url):
            if "/availability?" in url: return stock
            if "/instances?" in url: return INSTANCES
            if "/status?" in url:
                calls.append("confirm")
                raise monitor.MonitorError("fixture confirmation failed")
            return [EVENT]
        with patch.object(monitor,"request_json",side_effect=request), self.assertRaises(monitor.MonitorError):
            bush.observe(NOW,on_candidates=lambda items:calls.append("notice"))
        self.assertEqual(calls,["notice","confirm"])

EVENT = {'id': '121654APBHMLHQQSDQCBTGPQJKVRMKHRC', 'name': 'The Hungry Ghost', 'attribute_TicketVenue': 'Studio', 'attribute_WebsiteCategorisation': 'Production'}
INSTANCES = [{'isOnSale': True, 'event': {'id': '121654APBHMLHQQSDQCBTGPQJKVRMKHRC'}, 'start': '2026-10-29T20:00:00', 'startSellingAtWebUtc': '2026-06-12T10:37:00Z', 'stopSellingAtWebUtc': '2026-10-29T19:30:00Z', 'cancelled': False, 'id': '304553AHJRLDNJPJVKTRTBDDBKVBPNQCL', 'attribute_Location': 'Studio', 'attribute_PerformanceType': ''}, {'isOnSale': True, 'event': {'id': '121654APBHMLHQQSDQCBTGPQJKVRMKHRC'}, 'start': '2026-10-30T20:00:00', 'startSellingAtWebUtc': '2026-06-12T10:37:00Z', 'stopSellingAtWebUtc': '2026-10-30T19:30:00Z', 'cancelled': False, 'id': '304554ADRCGGTPVCNSLNCJJTCMKSBBLLH', 'attribute_Location': 'Studio', 'attribute_PerformanceType': ''}, {'isOnSale': True, 'event': {'id': '121654APBHMLHQQSDQCBTGPQJKVRMKHRC'}, 'start': '2026-10-31T15:00:00', 'startSellingAtWebUtc': '2026-06-12T10:37:00Z', 'stopSellingAtWebUtc': '2026-10-31T14:30:00Z', 'cancelled': False, 'id': '304739AMCKLNJGMTDNLDRLJDMVMVPQCVS', 'attribute_Location': 'Studio', 'attribute_PerformanceType': 'Matinee'}, {'isOnSale': True, 'event': {'id': '121654APBHMLHQQSDQCBTGPQJKVRMKHRC'}, 'start': '2026-10-31T20:00:00', 'startSellingAtWebUtc': '2026-06-12T10:37:00Z', 'stopSellingAtWebUtc': '2026-10-31T19:30:00Z', 'cancelled': False, 'id': '304555AGRTBNLSLVNLJQNJRGKCNKSMRTR', 'attribute_Location': 'Studio', 'attribute_PerformanceType': ''}]
INVENTORY = {'data': [{'eventInstanceId': '304553AHJRLDNJPJVKTRTBDDBKVBPNQCL', 'start': '2026-10-29T20:00:00', 'startUtc': '2026-10-29T20:00:00Z', 'capacity': 60, 'startSellingForCustomer': '2026-06-12T11:37:00', 'startSellingForCustomerUtc': '2026-06-12T10:37:00Z', 'availability': []}, {'eventInstanceId': '304554ADRCGGTPVCNSLNCJJTCMKSBBLLH', 'start': '2026-10-30T20:00:00', 'startUtc': '2026-10-30T20:00:00Z', 'capacity': 60, 'startSellingForCustomer': '2026-06-12T11:37:00', 'startSellingForCustomerUtc': '2026-06-12T10:37:00Z', 'availability': [{'priceBand': '604AGRPTGQTTPRPKPVCQNNLBRGTLVJRBR', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}, {'eventInstanceId': '304555AGRTBNLSLVNLJQNJRGKCNKSMRTR', 'start': '2026-10-31T20:00:00', 'startUtc': '2026-10-31T20:00:00Z', 'capacity': 60, 'startSellingForCustomer': '2026-06-12T11:37:00', 'startSellingForCustomerUtc': '2026-06-12T10:37:00Z', 'availability': [{'priceBand': '604AGRPTGQTTPRPKPVCQNNLBRGTLVJRBR', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}, {'eventInstanceId': '304739AMCKLNJGMTDNLDRLJDMVMVPQCVS', 'start': '2026-10-31T15:00:00', 'startUtc': '2026-10-31T15:00:00Z', 'capacity': 60, 'startSellingForCustomer': '2026-06-12T11:37:00', 'startSellingForCustomerUtc': '2026-06-12T10:37:00Z', 'availability': [{'priceBand': '604AGRPTGQTTPRPKPVCQNNLBRGTLVJRBR', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}]}
