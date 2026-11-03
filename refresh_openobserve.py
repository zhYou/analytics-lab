#!/usr/bin/env python3
"""Refresh explicitly labelled BI snapshots using OpenObserve's search API."""
from datetime import datetime, timezone
import json

from common import FIXTURES, ch, oo_search


def main():
    rows = oo_search("SELECT date_trunc('day',to_timestamp_micros(_timestamp)) AS day,channel,count(*) AS event_count,count(DISTINCT user_id) AS active_users FROM business_events GROUP BY day,channel ORDER BY day,channel")['hits']
    kinds = oo_search('SELECT event_name,count(*) AS event_count FROM business_events GROUP BY event_name ORDER BY event_name')['hits']
    if not rows or not kinds:
        raise RuntimeError('OpenObserve returned no aggregates; existing snapshot remains intact')
    for row in rows:
        row['day'] = row['day'][:10]
        row['event_count'] = int(row['event_count'])
        row['active_users'] = int(row['active_users'])
    ch('CREATE TABLE IF NOT EXISTS openobserve_demo.daily_events (day Date,channel String,event_count UInt64,active_users UInt64) ENGINE=MergeTree ORDER BY (day,channel)')
    ch('CREATE TABLE IF NOT EXISTS openobserve_demo.event_types (event_name String,event_count UInt64) ENGINE=MergeTree ORDER BY event_name')
    for name, data in [('daily_events', rows), ('event_types', kinds)]:
        staging = name + '_refresh'
        ch(f'CREATE TABLE IF NOT EXISTS openobserve_demo.{staging} AS openobserve_demo.{name}')
        ch(f'TRUNCATE TABLE openobserve_demo.{staging}')
        ch(f'INSERT INTO openobserve_demo.{staging} FORMAT JSONEachRow', data)
        ch(f'EXCHANGE TABLES openobserve_demo.{name} AND openobserve_demo.{staging}')
    summary = {'refreshed_at': datetime.now(timezone.utc).isoformat(), 'source': 'OpenObserve /api/default/_search',
               'daily_rows': len(rows), 'event_count': sum(row['event_count'] for row in rows)}
    (FIXTURES / 'openobserve-refresh.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
