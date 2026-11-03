"""Small HTTP helpers for the local synthetic analytics lab."""
import base64
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / 'fixtures'


def env():
    return dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if line and not line.startswith('#'))


def compose(*args, **kwargs):
    return subprocess.run(['docker', 'compose', *args], cwd=ROOT, check=True, **kwargs)


class Client:
    def __init__(self, base):
        self.base = base
        self.headers = {}
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, data=None, method=None):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        req = urllib.request.Request(self.base + path, body, {'Content-Type': 'application/json', **self.headers}, method=method)
        try:
            with self.opener.open(req, timeout=180) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'{method or "GET"} {path}: HTTP {error.code}: {error.read().decode()[:1400]}') from None


def basic(user, password):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()


def ch(query, records=None):
    settings = env()
    if records is None:
        url, body = 'http://127.0.0.1:8123/', query.encode()
    else:
        url = 'http://127.0.0.1:8123/?' + urllib.parse.urlencode({'query': query})
        body = b'\n'.join(json.dumps(row, ensure_ascii=False).encode() for row in records)
    req = urllib.request.Request(url, body, {'Authorization': basic('demo_admin', settings['SOURCE_PASSWORD'])})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.read().decode().strip()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'ClickHouse HTTP {error.code}: {error.read().decode()[:1400]}') from None


def mysql(sql):
    settings = env()
    return compose('exec', '-T', '-e', 'MYSQL_PWD', 'mysql', 'mysql', '-uroot', '--default-character-set=utf8mb4', '-N',
                   input=sql, text=True, capture_output=True, env={**os.environ, 'MYSQL_PWD': settings['SOURCE_PASSWORD']}).stdout


def oo():
    settings = env()
    client = Client('http://127.0.0.1:5080')
    client.headers['Authorization'] = basic(settings['ADMIN_EMAIL'], settings['ADMIN_PASSWORD'])
    return client


def oo_search(sql):
    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    return oo().call('/api/default/_search', {'query': {'sql': sql, 'start_time': manifest['start_us'], 'end_time': manifest['end_us'], 'from': 0, 'size': 1000}})


def wait_http(url, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise RuntimeError(f'Timed out waiting for {url}')
