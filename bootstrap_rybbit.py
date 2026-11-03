#!/usr/bin/env python3
"""Provision a private Rybbit demo and seed synthetic historical data only."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import http.cookiejar
import urllib.request

from common import Client, FIXTURES, compose, env, wait_http

BASE = 'http://localhost:3001'


class LocalClient(Client):
    def __init__(self):
        super().__init__(BASE)
        # Upstream marks cookies Secure even on localhost HTTP. Chromium treats
        # localhost as trustworthy; Python's cookie jar needs the same local
        # exception. This client only targets the fixed loopback demo origin.
        policy = http.cookiejar.DefaultCookiePolicy(secure_protocols=('https', 'wss', 'http'))
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar(policy)))
        self.headers['Origin'] = BASE

FUNNELS = [
    {'name': '注册会话 · 页面 → 注册 → 激活', 'steps': [
        {'type': 'page', 'value': '/signup', 'name': '注册页面'},
        {'type': 'event', 'value': 'signup_completed', 'name': '完成注册'},
        {'type': 'event', 'value': 'activation_completed', 'name': '完成激活'}]},
    {'name': '购买会话 · 定价 → 结算 → 支付', 'steps': [
        {'type': 'page', 'value': '/pricing', 'name': '查看定价'},
        {'type': 'event', 'value': 'checkout_started', 'name': '开始结算'},
        {'type': 'event', 'value': 'purchase_completed', 'name': '支付完成'}]},
]


def query(sql, rows=None):
    command = ['exec', '-T', 'rybbit-clickhouse', 'bash', '-c',
               'exec clickhouse-client --user default --password "$CLICKHOUSE_PASSWORD" --database analytics "$@"',
               '--', '--query', sql]
    data = None if rows is None else '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows)+'\n'
    result = compose(*command, input=data, text=True, capture_output=True)
    return result.stdout.strip()


def postgres(sql):
    return compose('exec', '-T', 'rybbit-postgres', 'psql', '-U', 'rybbit', '-d', 'analytics', '-v', 'ON_ERROR_STOP=1', '-tA',
                   input=sql, text=True, capture_output=True).stdout.strip()


def account():
    c = LocalClient()
    settings = env()
    # Check account existence separately: a bad existing password must never
    # trigger a signup attempt or silently replace credentials.
    email = settings['ADMIN_EMAIL'].replace("'", "''")
    exists = int(postgres(f'SELECT count(*) FROM "user" WHERE email=\'{email}\';'))
    if not exists:
        c.call('/api/auth/sign-up/email', {'name': 'Demo Admin', 'email': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']})
    c.call('/api/auth/sign-in/email', {'email': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']})
    orgs = c.call('/api/auth/organization/list')
    org = next((x for x in orgs if x['slug'] == 'analytics-lab'), None)
    if org is None:
        org = c.call('/api/auth/organization/create', {'name': 'Analytics Lab · 模拟业务', 'slug': 'analytics-lab'})
    c.call('/api/auth/organization/set-active', {'organizationId': org['id']})
    sites = c.call(f"/api/organizations/{org['id']}/sites")
    if isinstance(sites, dict):
        sites = sites['sites']
    site = next((x for x in sites if x['domain'] == 'demo.analytics.test'), None)
    if site is None:
        site = c.call(f"/api/organizations/{org['id']}/sites", {
            'name': '模拟 SaaS · 经营与行为', 'domain': 'demo.analytics.test', 'public': False,
            'saltUserIds': False, 'blockBots': False, 'sessionReplay': False})
    if 'data' in site:
        site = site['data']
    return c, org['id'], int(site['siteId'])


def records(site_id):
    users = {u['user_id']: u for u in map(json.loads, (FIXTURES/'users.jsonl').read_text().splitlines())}
    events = list(map(json.loads, (FIXTURES/'events.jsonl').read_text().splitlines()))
    source = json.loads((FIXTURES/'manifest.json').read_text())
    result = []
    paths = {'signup_completed': '/signup', 'activation_completed': '/onboarding', 'feature_used': '/features/report',
             'purchase_completed': '/checkout/success', 'purchase_refunded': '/billing', 'payment_failed': '/checkout/error'}
    channels = {'Organic': 'Organic Search', 'Paid Search': 'Paid Search', 'Social': 'Organic Social', 'Referral': 'Referral', 'Email': 'Email'}
    locations = {'华东': ('CN', 'CN-SH', 'Shanghai', 31.23, 121.47), '华南': ('CN', 'CN-GD', 'Shenzhen', 22.54, 114.06),
                 '华北': ('CN', 'CN-BJ', 'Beijing', 39.90, 116.40), '西南': ('CN', 'CN-SC', 'Chengdu', 30.57, 104.07),
                 '海外': ('US', 'US-CA', 'San Francisco', 37.77, -122.42)}
    for event in events:
        user = users[event['user_id']]
        country, region, city, lat, lon = locations[user['region']]
        mobile = user['device'] != 'Web'
        record = {'site_id': site_id, 'timestamp': event['event_time'], 'timestamp_ms': event['event_time']+'.000',
                  'session_id': event['session_id'], 'user_id': 'demo_'+str(user['user_id']),
                  'identified_user_id': 'demo_'+str(user['user_id']), 'hostname': 'demo.analytics.test',
                  'pathname': paths.get(event['event_name'], '/signup' if event['event_time'] < user['created_at'] else '/features'),
                  'page_title': 'Analytics Lab · 模拟业务', 'referrer': '', 'querystring': '', 'url_parameters': {},
                  'channel': channels[user['channel']], 'browser': 'Safari' if user['device'] == 'iOS' else 'Chrome',
                  'browser_version': '130', 'operating_system': {'Web': 'Windows', 'iOS': 'iOS', 'Android': 'Android'}[user['device']],
                  'operating_system_version': '15' if mobile else '11', 'language': 'zh-CN', 'timezone': 'UTC',
                  'country': country, 'region': region, 'city': city, 'lat': lat, 'lon': lon,
                  'screen_width': 390 if mobile else 1920, 'screen_height': 844 if mobile else 1080,
                  'device_type': 'mobile' if mobile else 'desktop',
                  'type': 'pageview' if event['event_name'] == 'page_view' else 'custom_event',
                  'event_name': '' if event['event_name'] == 'page_view' else event['event_name'],
                  'props': {'source_event_id': event['event_id'], 'channel': user['channel'], 'region': user['region'],
                            'device': user['device'], 'amount': event['amount'], 'synthetic': True}}
        result.append(record)
        if event['event_name'] in ('purchase_completed', 'payment_failed'):
            at = datetime.strptime(event['event_time'], '%Y-%m-%d %H:%M:%S')
            for minutes, kind, name, path in [(2, 'pageview', '', '/pricing'), (1, 'custom_event', 'checkout_started', '/checkout')]:
                time = (at-timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
                result.append({**record, 'timestamp': time, 'timestamp_ms': time+'.000', 'type': kind,
                               'event_name': name, 'pathname': path,
                               'props': {**record['props'], 'derived_demo_event': True}})
    summary = {'site_id': site_id, 'users': len(users), 'events': len(result), 'source_events': source['events'],
               'extra_checkout_events': len(result)-len(events), 'pageviews': sum(r['type']=='pageview' for r in result),
               'event_types': dict(Counter(r['event_name'] for r in result if r['type']=='custom_event')),
               'window': {'start_date': datetime.fromtimestamp(source['start_us']/1e6, timezone.utc).strftime('%Y-%m-%d'),
                          'end_date': source['anchor'][:10], 'time_zone': 'UTC'}}
    return users, result, summary


def expected_funnel(rows, steps):
    sessions = defaultdict(list)
    for row in rows:
        sessions[row['session_id']].append(row)
    counts = [0]*len(steps)
    for events in sessions.values():
        after = ''
        for i, step in enumerate(steps):
            matches = [e['timestamp_ms'] for e in events if e['timestamp_ms'] > after and
                       ((step['type']=='page' and e['type']=='pageview' and e['pathname']==step['value']) or
                        (step['type']=='event' and e['type']=='custom_event' and e['event_name']==step['value']))]
            if not matches:
                break
            after = min(matches)
            counts[i] += 1
    return counts


def seed_profiles(site_id, users):
    def literal(value):
        return "'"+str(value).replace("'", "''")+"'"
    values = []
    for user in users.values():
        traits = {'name': user['user_name'], 'channel': user['channel'], 'region': user['region'], 'device': user['device']}
        values.append(f"({site_id},{literal('demo_'+str(user['user_id']))},{literal(json.dumps(traits,ensure_ascii=False))}::jsonb,{literal(user['created_at'])})")
    for offset in range(0, len(values), 500):
        postgres('INSERT INTO user_profiles (site_id,user_id,traits,created_at) VALUES '+','.join(values[offset:offset+500])+
                 ' ON CONFLICT(site_id,user_id) DO UPDATE SET traits=excluded.traits;')


def main():
    wait_http(BASE+'/api/health')
    c, organization_id, site_id = account()
    users, rows, summary = records(site_id)
    count = int(query(f'SELECT count() FROM events WHERE site_id={site_id}'))
    if count and count != len(rows):
        raise RuntimeError(f'Rybbit site has {count} records; expected {len(rows)}. Refusing to overwrite or duplicate data.')
    if not count:
        for start in range(0,len(rows),10000):
            query('INSERT INTO events FORMAT JSONEachRow', rows[start:start+10000])
    seed_profiles(site_id, users)
    existing = c.call(f'/api/sites/{site_id}/funnels')['data']
    funnels = []
    for definition in FUNNELS:
        previous = next((x for x in existing if x['name']==definition['name']), None)
        payload = dict(definition)
        if previous:
            payload['reportId'] = previous['id']
        saved = c.call(f'/api/sites/{site_id}/funnels', payload)
        funnels.append({**definition, 'id': saved['funnelId'], 'expected_sessions': expected_funnel(rows,definition['steps'])})
    summary.update(organization_id=organization_id, funnels=funnels)
    (FIXTURES/'rybbit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='funnels'},ensure_ascii=False),flush=True)
    for funnel in funnels:
        print(funnel['name'],funnel['expected_sessions'],flush=True)


if __name__ == '__main__':
    main()
