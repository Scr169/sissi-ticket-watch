import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor
import rsc_as_you_like_it as rsc


class RSCTests(unittest.TestCase):
    def setUp(self):
        self.calendar = json.loads(Path(__file__).with_name('rsc_calendar_fixture.json').read_text())
        self.now = monitor.date('2026-11-05T10:00:00Z')

    def test_all_three_remaining_dates_and_today_excluded_even_when_open(self):
        self.calendar['rows'][1]['status'] = 'Book Tickets'
        result = rsc.parse_calendar(self.calendar, self.now)
        self.assertEqual(result, {'total': 3, 'candidates': []})
        self.calendar['rows'][2]['status'] = 'Book Tickets'
        result = rsc.parse_calendar(self.calendar, self.now)
        self.assertEqual([r['id'] for r in result['candidates']], ['62530'])

    def test_missing_mismatched_duplicate_unknown_are_failures_not_sold_out(self):
        variants = []
        d = copy.deepcopy(self.calendar); d['rows'].pop(); variants.append(d)
        d = copy.deepcopy(self.calendar); d['rows'].append(d['rows'][2]); variants.append(d)
        d = copy.deepcopy(self.calendar); d['rows'][2]['url'] = 'https://example.com'; variants.append(d)
        d = copy.deepcopy(self.calendar); d['rows'][2]['time'] = '1:30pm'; variants.append(d)
        d = copy.deepcopy(self.calendar); d['rows'][2]['status'] = 'Loading'; variants.append(d)
        d = copy.deepcopy(self.calendar); d['title'] = 'Another show'; variants.append(d)
        for data in variants:
            with self.subTest(data=data), self.assertRaises(monitor.MonitorError):
                rsc.parse_calendar(data, self.now)

    def test_started_performances_disappear_from_scope_and_final_cutoff(self):
        self.assertEqual(rsc.parse_calendar(self.calendar, monitor.date('2026-11-07T14:00:00Z'))['total'], 1)
        with patch('rsc_as_you_like_it.observe', side_effect=AssertionError('must not read')):
            with patch('monitor.datetime') as clock:
                clock.now.return_value = rsc.END
                self.assertIsNone(rsc.run())

    def test_actual_ordinary_seat_icons_require_full_price_not_disabled_rate(self):
        data = json.loads(Path(__file__).with_name('rsc_seats_fixture.json').read_text())
        candidate = {'url': data['url'], 'start': '2026-11-05T19:30:00+00:00'}
        result = rsc.confirm_booking(candidate, data)
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['seats'], [{'seat': 'G4', 'price': '£65.00'},
                                         {'seat': 'G62', 'price': '£75.00'}, {'seat': 'G63', 'price': '£75.00'}])
        # A map minimum £18 alone cannot verify ordinary public inventory.
        data['prices'][0]['full'] = []; data['prices'][1]['full'] = []
        try:
            result = rsc.confirm_booking(candidate, data)
        except monitor.MonitorError:
            result = None
        self.assertIsNone(result)

    def test_selected_wheelchair_disabled_and_mismatched_booking_rejected(self):
        data = json.loads(Path(__file__).with_name('rsc_seats_fixture.json').read_text())
        candidate = {'url': data['url'], 'start': '2026-11-05T19:30:00+00:00'}
        data['seats'][0]['disabled'] = True
        data['seats'][1]['pressed'] = 'true'
        data['seats'][2]['icon'] = '#tn-syos-seat-map-icon-wheelchair'
        self.assertIsNone(rsc.confirm_booking(candidate, data))
        data['selected'] = 'Friday 06 Nov 2026 7:30pm (Limited Availability)'
        with self.assertRaises(monitor.MonitorError): rsc.confirm_booking(candidate, data)

    def test_only_in_scope_links_are_opened_and_early_signal_precedes_confirmation(self):
        events = []
        self.calendar['rows'][1]['status'] = 'Book Tickets'
        self.calendar['rows'][2]['status'] = 'Book Tickets'
        with patch('rsc_as_you_like_it.RscBrowser') as cls:
            browser = cls.return_value.__enter__.return_value
            browser.calendar.return_value = self.calendar
            browser.confirm.side_effect = lambda c: events.append(c['id'])
            result = rsc.observe(self.now, lambda c: events.append('early'))
        self.assertEqual(events, ['early', '62530'])
        self.assertEqual(result['total'], 3)


if __name__ == '__main__': unittest.main()
