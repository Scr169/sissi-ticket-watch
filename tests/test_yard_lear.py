import copy
import unittest
from unittest.mock import patch
import monitor
import yard_lear as lear

NOW=monitor.date("2026-10-29T02:00:00Z")
STATUS={"name":"The Yard Theatre 2026","available":0,"capacity":224,"wheelchairAvailable":3,"specialAvailable":4,"lockInfoAvailable":[{"quantity":5}]}

class LearTests(unittest.TestCase):
    def parse(self, instances=None, stock=None, now=NOW):
        return lear.parse_inventory(INSTANCES if instances is None else instances, INVENTORY if stock is None else stock, now)

    def request(self, url):
        if "/status?" in url: return STATUS
        if "/instances?" in url: return INSTANCES
        if "/availability?" in url: return INVENTORY
        return EVENTS

    def test_exact_lear_ignores_gala_but_requires_production_identity(self):
        lear.select_event(EVENTS)
        for events in [EVENTS[1:],[],[dict(EVENTS[0],name="King Lear")],[dict(EVENTS[0],webEventId="THEGALA")],EVENTS+EVENTS]:
            with self.subTest(events=events),self.assertRaises(monitor.MonitorError):lear.select_event(events)
        self.assertEqual(self.parse()["total"],3)
        self.assertEqual(self.parse()["candidates"],[])

    def test_wrong_production_or_seating_plan_is_unknown(self):
        for change in [{"event":{"id":EVENTS[1]["id"]}},{"planId":"OTHER"}]:
            rows=copy.deepcopy(INSTANCES);rows[0].update(change)
            with self.assertRaises(monitor.MonitorError):self.parse(rows)

    def test_missing_duplicate_mismatched_and_invalid_inventory_fail(self):
        for stock in [{},{"data":[]},{"data":INVENTORY["data"][:-1]},{"data":INVENTORY["data"]*2}]:
            with self.assertRaises(monitor.MonitorError):self.parse(stock=stock)
        for value in [None,True,-1,"1"]:
            stock=copy.deepcopy(INVENTORY);stock["data"][0]["availability"][0]["count"]=value
            with self.assertRaises(monitor.MonitorError):self.parse(stock=stock)
        stock=copy.deepcopy(INVENTORY);stock["data"][0]["start"]="2026-11-17T19:00:00"
        with self.assertRaises(monitor.MonitorError):self.parse(stock=stock)

    def test_january_final_matinee_and_evening_and_started_shows(self):
        self.assertEqual(self.parse(now=monitor.date("2027-01-02T12:00:00Z"))["total"],2)
        self.assertEqual(self.parse(now=monitor.date("2027-01-02T14:30:00Z"))["total"],1)
        with self.assertRaises(monitor.MonitorError):self.parse(now=lear.END)
        rows=copy.deepcopy(INSTANCES);rows[0]["attribute_Information"]="Press Night"
        stock=copy.deepcopy(INVENTORY);stock["data"][0]["availability"][0]["count"]=1
        self.assertEqual(self.parse(rows,stock)["candidates"],[])
        rows[0]["attribute_Information"]="";rows[0]["startSellingAtWebUtc"]="2026-11-17T00:00:00Z"
        self.assertEqual(self.parse(rows,stock)["candidates"],[])

    def test_early_signal_precedes_confirmation_and_uses_correct_booking(self):
        stock=copy.deepcopy(INVENTORY);stock["data"][0]["availability"][0]["count"]=1
        calls=[]
        def request(url):
            if "/availability?" in url:return stock
            if "/status?" in url:
                calls.append("confirm")
                raise monitor.MonitorError("fixture timeout")
            return self.request(url)
        def notice(items):
            calls.append("notice")
            self.assertIn("https://tickets.theyardtheatre.co.uk/theyard/website/ChooseSeats.aspx?EventInstanceId=",items[0]["url"])
        with patch.object(monitor,"request_json",side_effect=request),self.assertRaises(monitor.MonitorError):lear.observe(NOW,on_candidates=notice)
        self.assertEqual(calls,["notice","confirm"])

    def test_access_and_eligibility_counts_are_never_ordinary_stock(self):
        stock=copy.deepcopy(INVENTORY);stock["data"][0]["availability"]=[]
        item=self.parse(stock=stock)["fallback"][0]
        with patch.object(monitor,"request_json",return_value=STATUS):self.assertIsNone(lear.read_status(item))
        with patch.object(monitor,"request_json",return_value=dict(STATUS,available=2)):
            self.assertEqual(lear.read_status(item)["count"],2)
        with patch.object(monitor,"request_json",return_value=dict(STATUS,name="OTHER")),self.assertRaises(monitor.MonitorError):lear.read_status(item)

    def test_empty_bands_are_explicitly_checked_not_assumed_zero(self):
        stock=copy.deepcopy(INVENTORY);stock["data"][0]["availability"]=[]
        for quantity in [0,1]:
            calls=[]
            def request(url):
                if "/availability?" in url:return stock
                if "/status?" in url:return dict(STATUS,available=quantity)
                return self.request(url)
            with patch.object(monitor,"request_json",side_effect=request):
                result=lear.observe(NOW,on_candidates=lambda items:calls.append(list(items)))
            self.assertEqual(len(calls),1)
            self.assertEqual(len(calls[0]),quantity)
            self.assertEqual(len(result["available"]),quantity)
        with patch.object(monitor,"request_json",side_effect=[EVENTS,INSTANCES,stock,{}]),self.assertRaises(monitor.MonitorError):lear.observe(NOW)

    def test_sold_out_complete_read_is_quiet_and_needs_no_login(self):
        calls=[]
        with patch.object(monitor,"request_json",side_effect=self.request) as read:
            result=lear.observe(NOW,on_candidates=calls.append)
        self.assertEqual(result["available"],[])
        self.assertEqual(calls,[[]])
        self.assertEqual(read.call_count,3)
        self.assertIn("需自行登录",lear.alert_body([],NOW))

EVENTS=[{'id': '83436AJGHHQJMSMGNGCSMSMBTGNPCVLHT', 'name': 'Lear', 'webEventId': 'LEAR', 'webUrl': 'https://www.theyardtheatre.co.uk/events/lear'}, {'id': '87636ATRQVKQRRTRNBVHHTMHJDDSHHKNL', 'name': 'Lear: The Gala', 'webEventId': 'THEGALA', 'webUrl': ''}]
INSTANCES=[{'id': '145274AGTMPMQPMRMDGCVRJSBKLDGTKKH', 'event': {'id': '83436AJGHHQJMSMGNGCSMSMBTGNPCVLHT'}, 'planId': '6010ATSSNGRDNNRDDDNRQJKDQBNQMMLNT', 'start': '2026-11-17T19:30:00', 'isOnSale': True, 'cancelled': False, 'startSellingAtWebUtc': '2026-06-22T11:00:00Z', 'stopSellingAtWebUtc': '2026-11-17T18:30:00Z'}, {'id': '147473AHLVPHQMDVRBGPQDTGBCVVDKHKT', 'event': {'id': '83436AJGHHQJMSMGNGCSMSMBTGNPCVLHT'}, 'planId': '6010ATSSNGRDNNRDDDNRQJKDQBNQMMLNT', 'start': '2027-01-02T14:30:00', 'isOnSale': True, 'cancelled': False, 'startSellingAtWebUtc': '2026-06-22T11:00:00Z', 'stopSellingAtWebUtc': '2027-01-02T13:30:00Z'}, {'id': '145878AHLCPGTDKHKDGSHQTPLJMCHHKDS', 'event': {'id': '83436AJGHHQJMSMGNGCSMSMBTGNPCVLHT'}, 'planId': '6010ATSSNGRDNNRDDDNRQJKDQBNQMMLNT', 'start': '2027-01-02T19:30:00', 'isOnSale': True, 'cancelled': False, 'startSellingAtWebUtc': '2026-06-22T11:00:00Z', 'stopSellingAtWebUtc': '2027-01-02T18:30:00Z'}]
INVENTORY={'data': [{'eventInstanceId': '145274AGTMPMQPMRMDGCVRJSBKLDGTKKH', 'start': '2026-11-17T19:30:00', 'startUtc': '2026-11-17T19:30:00Z', 'capacity': 224, 'startSellingForCustomer': '2026-06-22T12:00:00', 'startSellingForCustomerUtc': '2026-06-22T11:00:00Z', 'availability': [{'priceBand': '202AVGMPQTQBQRCSGKLRJQMMVGMLJNDVV', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '805ALKPTHPBRKDRDMHCLJMSQTSLPDJRBJ', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4418AMNVDRDDBDHGBLRSKKNHSGSQGVKJM', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4417ALKKPHJLGNLDCLCTLMJLJDNLHTMGS', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}, {'eventInstanceId': '147473AHLVPHQMDVRBGPQDTGBCVVDKHKT', 'start': '2027-01-02T14:30:00', 'startUtc': '2027-01-02T14:30:00Z', 'capacity': 224, 'startSellingForCustomer': '2026-06-22T12:00:00', 'startSellingForCustomerUtc': '2026-06-22T11:00:00Z', 'availability': [{'priceBand': '202AVGMPQTQBQRCSGKLRJQMMVGMLJNDVV', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '805ALKPTHPBRKDRDMHCLJMSQTSLPDJRBJ', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4419ACDQCKHPDNMKJKHLHRHKNMKHRVGSM', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4417ALKKPHJLGNLDCLCTLMJLJDNLHTMGS', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4418AMNVDRDDBDHGBLRSKKNHSGSQGVKJM', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}, {'eventInstanceId': '145878AHLCPGTDKHKDGSHQTPLJMCHHKDS', 'start': '2027-01-02T19:30:00', 'startUtc': '2027-01-02T19:30:00Z', 'capacity': 224, 'startSellingForCustomer': '2026-06-22T12:00:00', 'startSellingForCustomerUtc': '2026-06-22T11:00:00Z', 'availability': [{'priceBand': '202AVGMPQTQBQRCSGKLRJQMMVGMLJNDVV', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '805ALKPTHPBRKDRDMHCLJMSQTSLPDJRBJ', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4417ALKKPHJLGNLDCLCTLMJLJDNLHTMGS', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4418AMNVDRDDBDHGBLRSKKNHSGSQGVKJM', 'status': 'Available', 'count': 0, 'ticketTypes': []}, {'priceBand': '4419ACDQCKHPDNMKJKHLHRHKNMKHRVGSM', 'status': 'Available', 'count': 0, 'ticketTypes': []}]}]}
