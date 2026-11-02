import copy
import json
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import hebe
import monitor

FIXTURE = json.loads(Path(__file__).with_name('hebe_fixture.json').read_text())
NOW = datetime.fromisoformat('2026-11-01T12:00:00+00:00')


def opened():
    f = copy.deepcopy(FIXTURE)
    for r in f['live']['result']['event'] + f['live']['result']['session']:
        r.update(status='onsale', saleEnd='2026-12-20T18:30:00+08:00')
    for r in f['stock']['result']['product'] + f['stock']['result']['ticketArea']:
        r.update(status='onsale', saleEnd='2026-12-20T18:30:00+08:00')
    f['stock']['result']['ticketArea'][0]['count'] = 1
    return f


def parse(f, now=NOW):
    return hebe.parse_sessions(f['event'], f['sessions'], f['live'], now)


def confirm(f):
    candidate = parse(f)['candidates'][0]
    return hebe.confirm_stock(candidate,
        [{'productId':'p000017936','ticketAreaId':'a000010041','price':5200}],
        {'a000010041':{'name':'特1區5200'}}, f['stock'], NOW)


class HebeTests(unittest.TestCase):
    def test_http_403_checks_full_official_application_once(self):
        page={'url':hebe.SHOW,'heading':hebe.TITLE,'rows':[{'text':hebe.TITLE+f'（12/{int(day[-2:])}場次） '+day+' '+time+' 台北小巨蛋 銷售一空','buttons':[]} for _,day,time in hebe.SESSIONS.values()]}
        with patch.object(hebe,'read_source',side_effect=HTTPError(hebe.SHOW,403,'Forbidden',None,None)) as read, patch.object(hebe,'PublicBrowser') as browser:
            browser.return_value.__enter__.return_value.read_calendar.return_value=page
            result=hebe.observe(NOW)
        self.assertEqual(result['total'],6)
        self.assertEqual(result['available'],[])
        self.assertEqual(read.call_count,1)

    def test_chrome_refusal_remains_failure_without_another_transport(self):
        with patch.object(hebe,'read_source',side_effect=HTTPError(hebe.SHOW,403,'Forbidden',None,None)), patch.object(hebe,'PublicBrowser') as browser:
            browser.return_value.__enter__.return_value.read_calendar.side_effect=monitor.MonitorError('Chrome refused')
            with self.assertRaisesRegex(monitor.MonitorError,'Chrome refused'): hebe.observe(NOW)

    def test_rendered_partial_or_duplicate_calendar_is_failure(self):
        page={'url':hebe.SHOW,'heading':hebe.TITLE,'rows':[{'text':hebe.TITLE+f'（12/{int(day[-2:])}場次） '+day+' '+time+' 台北小巨蛋 銷售一空','buttons':[]} for _,day,time in hebe.SESSIONS.values()]}
        bad=copy.deepcopy(page);bad['rows'][-1]=bad['rows'][0]
        with self.assertRaises(monitor.MonitorError):hebe.parse_rendered_calendar(bad,NOW)
        bad=copy.deepcopy(page);bad['rows'].pop()
        with self.assertRaises(monitor.MonitorError):hebe.parse_rendered_calendar(bad,NOW)

    def test_rendered_booking_signal_is_not_confirmed_stock(self):
        page={'url':hebe.SHOW,'heading':hebe.TITLE,'rows':[{'text':hebe.TITLE+f'（12/{int(day[-2:])}場次） '+day+' '+time+' 台北小巨蛋 銷售一空','buttons':[]} for _,day,time in hebe.SESSIONS.values()]}
        page['rows'][0]['text']=page['rows'][0]['text'].replace('銷售一空','立即購買')
        page['rows'][0]['buttons']=[{'text':'立即購買'}]
        seen=[]
        with patch.object(hebe,'read_source',side_effect=HTTPError(hebe.SHOW,403,'Forbidden',None,None)),patch.object(hebe,'PublicBrowser') as browser:
            browser.return_value.__enter__.return_value.read_calendar.return_value=page
            with self.assertRaisesRegex(monitor.MonitorError,'stock remains unverified'):hebe.observe(NOW,on_candidates=lambda c:seen.extend(c))
        self.assertEqual(len(seen),1)
        self.assertNotIn('count',seen[0])

    def test_other_http_errors_are_not_retried_in_a_browser(self):
        with patch.object(hebe,'read_source',side_effect=HTTPError(hebe.SHOW,503,'Unavailable',None,None)), patch.object(hebe,'PublicBrowser') as browser:
            with self.assertRaises(HTTPError): hebe.observe(NOW)
        browser.assert_not_called()

    def test_actual_six_sold_out_rows_match(self):
        self.assertEqual(parse(FIXTURE), {'total':6,'candidates':[]})

    def test_lottery_or_wrong_venue_not_accepted(self):
        for key, value in [('event_id','afaf206f48c75998345655952851c853'),
                           ('lotteryDeadline','2026-10-08'), ('location','Other venue')]:
            f = copy.deepcopy(FIXTURE); f['event'][key] = value
            with self.assertRaises(monitor.MonitorError): parse(f)

    def test_missing_duplicate_or_failed_api_never_means_sold_out(self):
        for change in ('missing', 'duplicate', 'error'):
            f=copy.deepcopy(FIXTURE)
            if change=='missing': f['live']['result']['session'].pop()
            if change=='duplicate': f['live']['result']['session'].append(f['live']['result']['session'][0])
            if change=='error': f['live']['errCode']='999'
            with self.assertRaises(monitor.MonitorError): parse(f)

    def test_date_mismatch_or_unknown_status_is_failure(self):
        for key, value in [('sessionStart','2026-12-01T00:00:00+08:00'),('status','loading')]:
            f=copy.deepcopy(FIXTURE);f['live']['result']['session'][0][key]=value
            with self.assertRaises(monitor.MonitorError): parse(f)

    def test_taipei_start_time_excludes_started_only(self):
        f=opened();r=parse(f,datetime.fromisoformat('2026-12-12T10:30:00+00:00'))
        self.assertEqual(r['total'],5)
        self.assertTrue(r['candidates'][0]['when'].startswith('2026-12-13'))
        self.assertEqual(hebe.END.isoformat(),'2026-12-20T18:30:00+08:00')

    def test_early_signal_precedes_stock_read_failure(self):
        f=opened();seen=[]
        with patch.object(hebe,'static',side_effect=[f['event'],f['sessions'],monitor.MonitorError('stock unavailable')]), patch.object(hebe,'live',return_value=f['live']):
            with self.assertRaises(monitor.MonitorError): hebe.observe(NOW,on_candidates=lambda items:seen.extend(items))
        self.assertEqual(len(seen),6)

    def test_explicit_ordinary_area_stock_and_price_confirmed(self):
        item=confirm(opened())
        self.assertEqual(item['count'],1)
        self.assertEqual(item['areas'][0]['price'],5200)

    def test_missing_count_never_confirms_or_means_zero(self):
        f=opened();f['stock']['result']['ticketArea'][0].pop('count')
        with self.assertRaises(monitor.MonitorError): confirm(f)

    def test_zero_stock_and_restricted_inventory_do_not_confirm(self):
        cases=[('ticketArea','count',0),('product','disabilitiesType',1),
               ('product','hidden',True),('product','isProtected',True),
               ('product','serialKey','members'),('ticketArea','lock',True)]
        for kind,key,value in cases:
            f=opened();f['stock']['result'][kind][0][key]=value
            self.assertIsNone(confirm(f))

    def test_inventory_cross_performance_and_expired_sale_are_rejected(self):
        f=opened();f['stock']['result']['product'][0]['sessionId']='s000002289'
        with self.assertRaises(monitor.MonitorError): confirm(f)
        f=opened();f['live']['result']['event'][0]['saleEnd']='2026-10-27T15:45:00+08:00'
        with self.assertRaises(monitor.MonitorError): confirm(f)

    def test_notifications_label_taipei_and_twd(self):
        f=opened();item=confirm(f)
        early=hebe.candidate_body('田馥甄《要去什麼地方》',[item],NOW)
        self.assertIn('台北时间',early)
        self.assertNotIn('伦敦时间',early)
        self.assertIn('尚不能确认有票',early)
        self.assertIn('NT$5,200',hebe.alert_body([item],NOW))

    def test_custom_early_formatter_is_used_by_shared_notification(self):
        class GH:
            repo='fixture/repo'
            def __init__(self): self.notices=[]
            def state(self): return {},None
            def save(self,state,sha): pass
            def notify(self,title,body,marker): self.notices.append((title,body));return 'ack'
        gh=GH()
        def observer(now,on_candidates):
            on_candidates([{'key':'fixture','when':'2026-12-12 18:30','url':hebe.SHOW}])
            return {'total':6,'available':[],'source':'test'}
        monitor.run(config={'name':hebe.TITLE,'prefix':'hebe','end':datetime(2100,1,1,tzinfo=hebe.TAIPEI),
                            'format_candidate':hebe.candidate_body}, observer=observer,github=lambda:gh)
        self.assertTrue(gh.notices[0][0].startswith('田馥甄《要去什麼地方》｜'))
        self.assertIn('台北时间',gh.notices[0][1])
        self.assertNotIn('伦敦时间',gh.notices[0][1])


if __name__=='__main__':
    unittest.main()
