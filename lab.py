#!/usr/bin/env python3
"""Lifecycle entry point for the independent, loopback-only analytics demo."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from common import ROOT, FIXTURES, compose, env, wait_http


def credentials():
    target = ROOT / '.env'
    if not target.exists():
        values = {'ADMIN_EMAIL': 'admin@analytics.test', 'ADMIN_PASSWORD': 'Demo-' + secrets.token_urlsafe(15) + '!',
                  'SOURCE_PASSWORD': secrets.token_hex(20), 'READER_PASSWORD': secrets.token_hex(20),
                  'METADATA_PASSWORD': secrets.token_hex(20), 'SUPERSET_SECRET_KEY': secrets.token_hex(40), 'RYBBIT_AUTH_SECRET': secrets.token_hex(32)}
        # Create with restrictive permissions before writing any secrets.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    os.chmod(target, 0o600)
    if 'RYBBIT_AUTH_SECRET' not in env():
        with target.open('a') as stream:
            stream.write('RYBBIT_AUTH_SECRET='+secrets.token_hex(32)+'\n')


def access_file():
    settings = env()
    superset = json.loads((FIXTURES/'superset.json').read_text())
    metabase = json.loads((FIXTURES/'metabase.json').read_text())
    rybbit = json.loads((FIXTURES/'rybbit.json').read_text())
    lines = ['Analytics Lab — local access (do not publish)', '',
             'Superset: http://localhost:8088  username: admin',
             f"Metabase: http://localhost:3000  username: {settings['ADMIN_EMAIL']}",
             f"Rybbit: http://localhost:3001  username: {settings['ADMIN_EMAIL']}",
             f"OpenObserve: http://localhost:5080  username: {settings['ADMIN_EMAIL']}",
             f"Password for all four demo applications: {settings['ADMIN_PASSWORD']}", '',
             *[f"Superset / {d['name']}: http://localhost:8088/superset/dashboard/{d['slug']}/" for d in superset['dashboards']],
             *[f"Metabase / {d['name']}: http://localhost:3000/dashboard/{d['id']}" for d in metabase['dashboards']],
             *[f"Rybbit / {label}: http://localhost:3001/{rybbit['site_id']}/{route}?wellKnown=all-time" for label,route in [('概览','main'),('事件','events'),('会话漏斗','funnels'),('首访留存','retention'),('用户','users'),('路径','journeys')]],
             '', 'SQL read-only user: demo_reader', f"SQL reader password: {settings['READER_PASSWORD']}",
             'ClickHouse HTTP: 127.0.0.1:8123, databases analytics_demo / openobserve_demo',
             'MySQL: 127.0.0.1:3307, database analytics_demo',
             'OpenObserve stream: default / business_events',
             'OpenObserve BI connections query API-derived ClickHouse snapshots; refresh with lab.py refresh.']
    target = ROOT/'ACCESS.txt'
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    os.chmod(target, 0o600)
    print('Access details saved privately in ACCESS.txt', flush=True)


def verify():
    subprocess.run([sys.executable, str(ROOT/'verify.py')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'verify_rybbit.py')], cwd=ROOT, check=True)


def up():
    credentials()
    FIXTURES.mkdir(exist_ok=True)
    (ROOT/'logs').mkdir(exist_ok=True)
    compose('build', 'superset-init')
    compose('up', '-d', '--wait', '--wait-timeout', '240', 'metadata', 'clickhouse', 'mysql', 'openobserve', 'metabase')
    import seed
    import refresh_openobserve
    import bootstrap_metabase
    seed.main()
    refresh_openobserve.main()
    compose('up', '-d', '--wait', '--wait-timeout', '360', 'superset')
    # Reload the mounted Python configuration on repeated deployments too.
    compose('restart', 'superset')
    wait_http('http://127.0.0.1:8088/health')
    result = compose('exec', '-T', 'superset', 'cat', '/app/superset_home/demo-manifest.json', capture_output=True, text=True)
    (FIXTURES/'superset.json').write_text(result.stdout)
    bootstrap_metabase.main()
    compose('up', '-d', '--wait', '--wait-timeout', '360', 'rybbit')
    import bootstrap_rybbit
    bootstrap_rybbit.main()
    access_file()
    verify()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'stop', 'status', 'verify', 'refresh'])
    action = parser.parse_args().action
    if action == 'up':
        up()
    elif action == 'stop':
        compose('stop')
    elif action == 'status':
        compose('ps')
    elif action == 'verify':
        verify()
    else:
        import refresh_openobserve
        refresh_openobserve.main()
        verify()


if __name__ == '__main__':
    main()
