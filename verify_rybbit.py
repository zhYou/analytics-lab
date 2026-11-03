#!/usr/bin/env python3
"""Integration checks for the actual self-hosted Rybbit demo."""
import json
import unittest
import urllib.parse
import urllib.request
from common import Client, FIXTURES, env


def client():
    settings = env()
    from bootstrap_rybbit import LocalClient
    c = LocalClient()
    c.call('/api/auth/sign-in/email', {'email': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']})
    return c


class RybbitTests(unittest.TestCase):
    def test_health(self):
        try:
            with urllib.request.urlopen('http://localhost:3001/api/health', timeout=10) as response:
                self.assertEqual(response.status, 200)
        except OSError as error:
            self.fail(f'Rybbit is not ready: {error}')

    def test_seed_totals(self):
        from bootstrap_rybbit import query
        m = json.loads((FIXTURES/'rybbit.json').read_text())
        row = json.loads(query(f"SELECT count() AS events, uniqExact(user_id) AS users, countIf(type='pageview') AS pageviews FROM events WHERE site_id={m['site_id']} FORMAT JSONEachRow"))
        self.assertEqual(row['events'], m['events'])
        self.assertEqual(row['users'], m['users'])
        self.assertEqual(row['pageviews'], m['pageviews'])
        self.assertGreater(row['pageviews'], 0)

    def test_demo_is_private(self):
        m = json.loads((FIXTURES/'rybbit.json').read_text())
        with self.assertRaisesRegex(RuntimeError, r'HTTP (401|403)'):
            Client('http://localhost:3001').call(f"/api/sites/{m['site_id']}/overview")

    def test_native_analytics(self):
        m = json.loads((FIXTURES/'rybbit.json').read_text())
        c = client()
        root = f"/api/sites/{m['site_id']}"
        window = '?' + urllib.parse.urlencode(m['window'])
        saved = c.call(root+'/funnels')['data']
        expected_saved = {(x['id'], x['name']) for x in m['funnels']}
        actual_saved = {(x['id'], x['name']) for x in saved}
        self.assertTrue(expected_saved.issubset(actual_saved), 'Seeded funnels are missing or renamed')
        for funnel in m['funnels']:
            with self.subTest(funnel=funnel['name']):
                result = c.call(root+'/funnels/analyze'+window, {'steps': funnel['steps']})['data']
                counts = [int(x['sessions']) for x in result]
                self.assertEqual(counts, funnel['expected_sessions'])
                self.assertTrue(all(x >= y for x,y in zip(counts,counts[1:])))
                self.assertGreater(counts[-1], 0)
        retention = c.call(root+'/retention?mode=week&range=180')['data']
        self.assertTrue(retention['cohorts'])
        self.assertGreater(retention['maxPeriods'], 0)
        users = c.call(root+'/users'+window)
        self.assertTrue(users['data'])
        events = c.call(root+'/events'+window)
        self.assertTrue(events['data'])
        profile = c.call(root+'/users/demo_1'+window)
        self.assertTrue(profile['data'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
