#!/usr/bin/env python3
"""Generate and load a shared, deterministic 120-day synthetic dataset."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
import random

from common import FIXTURES, ch, env, mysql, oo, oo_search, wait_http


def generate():
    rng = random.Random(20261103)
    anchor_path = FIXTURES / 'anchor.txt'
    if not anchor_path.exists():
        anchor_path.write_text(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    now = datetime.fromisoformat(anchor_path.read_text())
    start = now.replace(hour=0, minute=0, second=0) - timedelta(days=120)
    channels = ['Organic', 'Paid Search', 'Social', 'Referral', 'Email']
    regions = ['华东', '华南', '华北', '西南', '海外']
    products = [('Starter', 49), ('Pro', 129), ('Team', 399), ('Enterprise', 1199)]
    users, orders, events = [], [], []

    def stamp(value):
        return value.strftime('%Y-%m-%d %H:%M:%S')

    def event(user, name, at, amount=0):
        if at > now:
            return
        events.append({'event_id': f'ev_{len(events) + 1:09d}', 'user_id': user['user_id'], 'event_name': name,
                       'event_time': stamp(at), 'session_id': f"s_{user['user_id']}_{at:%Y%m%d}",
                       'channel': user['channel'], 'region': user['region'], 'device': user['device'], 'amount': amount})

    for uid in range(1, 4001):
        day = int(rng.triangular(0, 119, 100))
        created = start + timedelta(days=day, hours=rng.randrange(24), minutes=rng.randrange(60))
        if created >= now:
            created = now - timedelta(hours=1)
        user = {'user_id': uid, 'user_name': f'Demo User {uid:04d}', 'created_at': stamp(created),
                'channel': rng.choices(channels, [35, 25, 18, 15, 7])[0], 'region': rng.choice(regions),
                'device': rng.choices(['Web', 'iOS', 'Android'], [50, 23, 27])[0]}
        users.append(user)
        event(user, 'page_view', created - timedelta(minutes=3))
        event(user, 'signup_completed', created)
        if rng.random() >= 0.79:
            continue
        activated = created + timedelta(minutes=rng.randint(4, 90))
        event(user, 'activation_completed', activated)
        age = min((now - created).days, 90)
        for offset in range(age + 1):
            probability = (0.61 * math.exp(-offset / 29) + 0.06) * (1.12 if user['channel'] == 'Referral' else 1)
            if offset == 0 or rng.random() < probability:
                at = activated + timedelta(days=offset, minutes=rng.randint(0, 300))
                event(user, 'feature_used', at)
                event(user, 'page_view', at - timedelta(minutes=1))
        if rng.random() < 0.48:
            first_order = activated + timedelta(hours=rng.randint(1, 24 * 12))
            for repeat in range(rng.randint(1, 5)):
                at = first_order + timedelta(days=repeat * rng.randint(7, 25))
                if at > now:
                    continue
                product, price = rng.choices(products, [40, 36, 19, 5])[0]
                amount = round(price * rng.choice([1, 1, 1, 2]) * rng.choice([1, 1, .9, .85]), 2)
                status = rng.choices(['paid', 'refunded', 'cancelled'], [85, 7, 8])[0]
                order = {'order_id': len(orders) + 1, 'user_id': uid, 'ordered_at': stamp(at), 'product': product,
                         'amount': amount, 'status': status, 'channel': user['channel'], 'region': user['region']}
                orders.append(order)
                if status != 'cancelled':
                    event(user, 'purchase_completed', at, amount)
                    if status == 'refunded':
                        event(user, 'purchase_refunded', at + timedelta(days=2), amount)
                else:
                    event(user, 'payment_failed', at, amount)

    manifest = {'users': len(users), 'orders': len(orders), 'events': len(events),
                'start_us': int((start - timedelta(days=1)).timestamp() * 1e6), 'end_us': int((now + timedelta(seconds=1)).timestamp() * 1e6),
                'anchor': now.isoformat(), 'net_revenue': round(sum(o['amount'] for o in orders if o['status'] == 'paid'), 2),
                'event_types': dict(Counter(e['event_name'] for e in events))}
    for name, rows in [('users', users), ('orders', orders), ('events', events)]:
        (FIXTURES / f'{name}.jsonl').write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n')
    (FIXTURES / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return users, orders, events, manifest


def create_clickhouse(users, orders, events):
    settings = env()
    statements = [
        'CREATE DATABASE IF NOT EXISTS analytics_demo',
        'CREATE DATABASE IF NOT EXISTS openobserve_demo',
        'CREATE TABLE IF NOT EXISTS analytics_demo.users (user_id UInt64, user_name String, created_at DateTime, channel String, region String, device String) ENGINE=MergeTree ORDER BY user_id',
        'CREATE TABLE IF NOT EXISTS analytics_demo.orders (order_id UInt64, user_id UInt64, ordered_at DateTime, product String, amount Decimal(12,2), status String, channel String, region String) ENGINE=MergeTree ORDER BY (toDate(ordered_at),order_id)',
        'CREATE TABLE IF NOT EXISTS analytics_demo.events (event_id String, user_id UInt64, event_name String, event_time DateTime, session_id String, channel String, region String, device String, amount Decimal(12,2)) ENGINE=MergeTree ORDER BY (toDate(event_time),user_id,event_time)',
        f"CREATE USER IF NOT EXISTS demo_reader IDENTIFIED WITH sha256_password BY '{settings['READER_PASSWORD']}'",
        'GRANT SELECT ON analytics_demo.* TO demo_reader',
        'GRANT SELECT ON openobserve_demo.* TO demo_reader',
    ]
    for statement in statements:
        ch(statement)
    for table, rows in [('users', users), ('orders', orders), ('events', events)]:
        count = int(ch(f'SELECT count() FROM analytics_demo.{table}'))
        if count == 0:
            ch(f'INSERT INTO analytics_demo.{table} FORMAT JSONEachRow', rows)
        elif count != len(rows):
            raise RuntimeError(f'{table} already contains unexpected data; refusing to replace it')
    views = {
        'daily_business': "SELECT toDate(ordered_at) AS day, sumIf(amount,status='paid') AS net_revenue, countIf(status='paid') AS paid_orders, countIf(status='refunded') AS refunded_orders FROM analytics_demo.orders GROUP BY day",
        'channel_revenue': "SELECT channel, sumIf(amount,status='paid') AS net_revenue, countIf(status='paid') AS paid_orders FROM analytics_demo.orders GROUP BY channel",
        'product_revenue': "SELECT product, sumIf(amount,status='paid') AS net_revenue, countIf(status='paid') AS paid_orders FROM analytics_demo.orders GROUP BY product",
        'daily_activity': "SELECT toDate(event_time) AS day, uniqExactIf(user_id,event_name='feature_used') AS active_users, countIf(event_name='signup_completed') AS signups, countIf(event_name='activation_completed') AS activations FROM analytics_demo.events GROUP BY day",
        'funnel_summary': "WITH levels AS (SELECT user_id, windowFunnel(604800)(event_time,event_name='signup_completed',event_name='activation_completed',event_name='purchase_completed') AS level FROM analytics_demo.events GROUP BY user_id) SELECT toUInt8(step) AS stage_order, multiIf(step=1,'1. 注册',step=2,'2. 激活','3. 7日内支付') AS stage, countIf(level>=step) AS users FROM levels CROSS JOIN (SELECT arrayJoin([1,2,3]) AS step) AS steps GROUP BY step ORDER BY step",
        'weekly_retention': "WITH sizes AS (SELECT toMonday(toDate(created_at)) AS cohort_week,count() AS cohort_users FROM analytics_demo.users GROUP BY cohort_week), retained AS (SELECT toMonday(toDate(u.created_at)) AS cohort_week,toUInt8(dateDiff('week',toMonday(toDate(u.created_at)),toMonday(toDate(e.event_time)))) AS week_index,uniqExact(e.user_id) AS retained_users FROM analytics_demo.events e INNER JOIN analytics_demo.users u ON e.user_id=u.user_id WHERE e.event_name='feature_used' GROUP BY cohort_week,week_index) SELECT s.cohort_week AS cohort_week,w.week_index AS week_index,s.cohort_users,ifNull(r.retained_users,0) AS retained_users,round(100.0*retained_users/s.cohort_users,2) AS retention_percent FROM sizes s CROSS JOIN (SELECT arrayJoin(range(8)) AS week_index) w LEFT JOIN retained r ON s.cohort_week=r.cohort_week AND w.week_index=r.week_index WHERE addWeeks(s.cohort_week,toInt32(w.week_index)+1)<=today()",
    }
    for name, sql in views.items():
        ch(f'CREATE OR REPLACE VIEW analytics_demo.{name} AS {sql}')


def create_mysql(users, orders):
    sql = "USE analytics_demo; SET NAMES utf8mb4; "
    sql += 'CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY,user_name VARCHAR(100),created_at DATETIME,channel VARCHAR(30),region VARCHAR(30),device VARCHAR(20));'
    sql += 'CREATE TABLE IF NOT EXISTS orders (order_id BIGINT PRIMARY KEY,user_id BIGINT,ordered_at DATETIME,product VARCHAR(40),amount DECIMAL(12,2),status VARCHAR(20),channel VARCHAR(30),region VARCHAR(30),INDEX idx_order_time(ordered_at),INDEX idx_user(user_id));'
    mysql(sql)
    for table, rows in [('users', users), ('orders', orders)]:
        count = int(mysql(f'SELECT count(*) FROM analytics_demo.{table};').strip())
        if count == len(rows):
            continue
        if count:
            raise RuntimeError(f'MySQL {table} has unexpected rows; refusing to replace it')
        keys = list(rows[0])
        for start in range(0, len(rows), 500):
            values = ','.join('(' + ','.join(json.dumps(row[key], ensure_ascii=False) for key in keys) + ')' for row in rows[start:start+500])
            mysql(f"INSERT INTO analytics_demo.{table} ({','.join(keys)}) VALUES {values};")
    mysql("CREATE OR REPLACE VIEW analytics_demo.customer_revenue AS SELECT u.user_id,u.user_name,u.channel,u.region,count(o.order_id) AS paid_orders,coalesce(sum(o.amount),0) AS net_revenue FROM analytics_demo.users u LEFT JOIN analytics_demo.orders o ON u.user_id=o.user_id AND o.status='paid' GROUP BY u.user_id,u.user_name,u.channel,u.region;")
    mysql("GRANT SELECT, SHOW VIEW ON analytics_demo.* TO 'demo_reader'@'%'; REVOKE INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, ALTER, CREATE TEMPORARY TABLES, LOCK TABLES, CREATE VIEW, CREATE ROUTINE, ALTER ROUTINE, EXECUTE, EVENT, TRIGGER ON analytics_demo.* FROM 'demo_reader'@'%';")


def create_openobserve(events, manifest):
    try:
        count = int(oo_search('SELECT count(*) AS total FROM business_events')['hits'][0]['total'])
    except RuntimeError as error:
        if 'not found' not in str(error).lower() and 'stream' not in str(error).lower():
            raise
        count = 0
    if count:
        if count != manifest['events']:
            raise RuntimeError('OpenObserve stream has unexpected rows; refusing duplicate ingestion')
        return
    client = oo()
    for start in range(0, len(events), 1500):
        batch = []
        for event in events[start:start+1500]:
            record = dict(event)
            record['_timestamp'] = int(datetime.strptime(record['event_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()*1e6)
            record['service'] = 'synthetic-commerce'
            batch.append(record)
        response = client.call('/api/default/business_events/_json', batch)
        for status in response.get('status', []):
            if status.get('failed', 0):
                raise RuntimeError(f'OpenObserve ingestion rejected records: {status}')
    print(f'OpenObserve ingested {len(events)} synthetic events', flush=True)


def main():
    FIXTURES.mkdir(exist_ok=True)
    wait_http('http://127.0.0.1:8123/ping')
    wait_http('http://127.0.0.1:5080/healthz')
    users, orders, events, manifest = generate()
    create_clickhouse(users, orders, events)
    create_mysql(users, orders)
    create_openobserve(events, manifest)
    print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
