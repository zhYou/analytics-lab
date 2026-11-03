#!/usr/bin/env python3
"""Integration checks against the actual local preview services."""
import base64
from decimal import Decimal
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def environment():
    return dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if line and not line.startswith('#'))


class Client:
    def __init__(self, base):
        self.base = base
        self.headers = {}
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, data=None, method=None):
        body = None if data is None else json.dumps(data).encode()
        headers = {'Content-Type': 'application/json', **self.headers}
        req = urllib.request.Request(self.base + path, body, headers, method=method)
        try:
            with self.opener.open(req, timeout=90) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise AssertionError(f'{method or "GET"} {path}: HTTP {error.code}: {error.read().decode()[:1200]}') from None


def clickhouse(query, user='demo_admin'):
    env = environment()
    password = env['SOURCE_PASSWORD'] if user == 'demo_admin' else env['READER_PASSWORD']
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    req = urllib.request.Request('http://127.0.0.1:8123/', query.encode(), {'Authorization': 'Basic ' + auth})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read().decode().strip()


def openobserve(query):
    env = environment()
    client = Client('http://127.0.0.1:5080')
    client.headers['Authorization'] = 'Basic ' + base64.b64encode(f"{env['ADMIN_EMAIL']}:{env['ADMIN_PASSWORD']}".encode()).decode()
    manifest = json.loads((ROOT / 'fixtures' / 'manifest.json').read_text())
    return client.call('/api/default/_search', {'query': {'sql': query, 'start_time': manifest['start_us'], 'end_time': manifest['end_us'], 'from': 0, 'size': 1000}})


class DemoTests(unittest.TestCase):
    def test_services_are_healthy(self):
        for url in ['http://127.0.0.1:8088/health', 'http://127.0.0.1:3000/api/health', 'http://127.0.0.1:5080/healthz']:
            with self.subTest(url=url):
                try:
                    with urllib.request.urlopen(url, timeout=10) as response:
                        self.assertEqual(response.status, 200)
                except (urllib.error.URLError, TimeoutError) as error:
                    self.fail(f'{url} is not ready: {error}')

    def test_sources_reconcile(self):
        manifest = json.loads((ROOT / 'fixtures' / 'manifest.json').read_text())
        for table in ['users', 'orders', 'events']:
            self.assertEqual(int(clickhouse(f'SELECT count() FROM analytics_demo.{table}')), manifest[table])
        env = environment()
        command = ['docker', 'compose', 'exec', '-T', '-e', 'MYSQL_PWD', 'mysql', 'mysql', '-uroot', '-N', '-e', 'SELECT count(*) FROM analytics_demo.users; SELECT count(*) FROM analytics_demo.orders;']
        result = subprocess.run(command, cwd=ROOT, env={**os.environ, 'MYSQL_PWD': env['SOURCE_PASSWORD']}, text=True, capture_output=True, check=True)
        self.assertEqual([int(x) for x in result.stdout.split()], [manifest['users'], manifest['orders']])
        expected_revenue = Decimal(str(manifest['net_revenue']))
        self.assertEqual(Decimal(clickhouse("SELECT sum(amount) FROM analytics_demo.orders WHERE status='paid'")), expected_revenue)
        result = subprocess.run(command[:-1] + ["SELECT SUM(amount) FROM analytics_demo.orders WHERE status='paid';"], cwd=ROOT, env={**os.environ, 'MYSQL_PWD': env['SOURCE_PASSWORD']}, text=True, capture_output=True, check=True)
        self.assertEqual(Decimal(result.stdout.strip()), expected_revenue)
        self.assertEqual(int(clickhouse('SELECT count() FROM analytics_demo.weekly_retention WHERE retention_percent<0 OR retention_percent>100')), 0)
        funnel = [int(x) for x in clickhouse('SELECT users FROM analytics_demo.funnel_summary ORDER BY stage_order').split()]
        self.assertEqual(len(funnel), 3)
        self.assertEqual(funnel[0], manifest['users'])
        self.assertTrue(funnel[0] >= funnel[1] >= funnel[2] > 0)
        result = openobserve('SELECT count(*) AS total FROM business_events')
        self.assertEqual(int(result['hits'][0]['total']), manifest['events'])
        self.assertEqual(int(clickhouse('SELECT sum(event_count) FROM openobserve_demo.daily_events')), manifest['events'])
        self.assertEqual(int(clickhouse('SELECT count() FROM analytics_demo.users', 'demo_reader')), manifest['users'])

    def test_superset_all_charts_execute(self):
        env = environment()
        client = Client('http://127.0.0.1:8088')
        token = client.call('/api/v1/security/login', {'username': 'admin', 'password': env['ADMIN_PASSWORD'], 'provider': 'db', 'refresh': True})['access_token']
        client.headers['Authorization'] = 'Bearer ' + token
        client.headers['X-CSRFToken'] = client.call('/api/v1/security/csrf_token/')['result']
        manifest = json.loads((ROOT / 'fixtures' / 'superset.json').read_text())
        self.assertGreaterEqual(len(manifest['dashboards']), 2)
        self.assertEqual(len(manifest['databases']), 3)
        for chart in manifest['charts']:
            with self.subTest(chart=chart['title']):
                result = client.call('/api/v1/chart/data', chart['query_context'])
                if chart['key'] == 'revenue':
                    expected = Decimal(str(json.loads((ROOT/'fixtures'/'manifest.json').read_text())['net_revenue']))
                    self.assertEqual(Decimal(str(result['result'][0]['data'][0]['净收入'])), expected)
                self.assertTrue(result.get('result'), result)
                for query in result['result']:
                    self.assertFalse(query.get('error'), query.get('error'))
                    self.assertGreater(len(query.get('data', [])), 0, chart['title'])

    def test_metabase_all_cards_execute(self):
        env = environment()
        client = Client('http://127.0.0.1:3000')
        client.headers['X-Metabase-Session'] = client.call('/api/session', {'username': env['ADMIN_EMAIL'], 'password': env['ADMIN_PASSWORD']})['id']
        manifest = json.loads((ROOT / 'fixtures' / 'metabase.json').read_text())
        self.assertEqual(len(manifest['databases']), 3)
        for dashboard in manifest['dashboards']:
            detail = client.call('/api/dashboard/' + str(dashboard['id']))
            self.assertGreater(len(detail['dashcards']), 0)
        for card in manifest['cards']:
            with self.subTest(card=card['name']):
                result = client.call(f"/api/card/{card['id']}/query", {})
                self.assertEqual(result.get('status'), 'completed', result.get('error'))
                self.assertGreater(len(result['data']['rows']), 0)

    def test_published_ports_are_loopback_only(self):
        result = subprocess.run(['docker', 'compose', 'ps', '--format', 'json'], cwd=ROOT, text=True, capture_output=True, check=True)
        services = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        for service in services:
            for port in service.get('Publishers') or []:
                if port.get('PublishedPort'):
                    self.assertEqual(port['URL'], '127.0.0.1', service['Service'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
