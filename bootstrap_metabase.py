#!/usr/bin/env python3
"""Set up the local Metabase instance through its authenticated API."""
import json

from common import Client, FIXTURES, env, wait_http
from dashboards import DATABASES, DASHBOARDS, CHARTS, sql_for


def main():
    wait_http('http://127.0.0.1:3000/api/health')
    settings = env()
    client = Client('http://127.0.0.1:3000')
    properties = client.call('/api/session/properties')
    token = properties.get('setup-token')
    if token:
        client.call('/api/setup', {'token': token,
                    'user': {'first_name': 'Demo', 'last_name': 'Admin', 'email': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']},
                    'prefs': {'site_name': 'Analytics Lab', 'allow_tracking': False}, 'database': None})
    session = client.call('/api/session', {'username': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']})
    client.headers['X-Metabase-Session'] = session['id']
    existing = client.call('/api/database')['data']
    databases = {}
    for key, (name, schema) in DATABASES.items():
        match = next((item for item in existing if item['name'] == name), None)
        if match is None:
            details = {'host': 'mysql' if key == 'mysql' else 'clickhouse', 'port': 3306 if key == 'mysql' else 8123,
                       'dbname': schema, 'user': 'demo_reader', 'password': settings['READER_PASSWORD'], 'ssl': False}
            if key == 'mysql':
                details['additional-options'] = 'allowPublicKeyRetrieval=true'
            match = client.call('/api/database', {'name': name, 'engine': 'mysql' if key == 'mysql' else 'clickhouse',
                                                 'details': details, 'is_full_sync': True, 'auto_run_queries': True})
        databases[key] = match
    collection_name = '经营与用户分析 · 演示'
    collection = next((row for row in client.call('/api/collection') if row['name'] == collection_name), None)
    if collection is None:
        collection = client.call('/api/collection', {'name': collection_name, 'description': '三数据源、同口径对比。全部为模拟数据。'})
    existing_cards = client.call('/api/card')
    cards = []
    for definition in CHARTS:
        kind = definition['kind']
        display = {'scalar': 'scalar', 'line': 'line', 'bar': 'bar', 'pie': 'pie', 'table': 'table', 'funnel': 'funnel', 'retention': 'table'}[kind]
        dimensions = definition.get('dimensions', [])
        visualization = {'graph.dimensions': dimensions[:1], 'graph.metrics': ['value'],
                         'graph.show_values': kind == 'bar', 'graph.x_axis.title_text': dimensions[0] if dimensions else '',
                         'graph.y_axis.title_text': definition['label']}
        if kind == 'pie':
            visualization.update({'pie.dimension': dimensions[0], 'pie.metric': 'value'})
        if kind == 'funnel':
            visualization.update({'funnel.dimension': dimensions[0], 'funnel.metric': 'value'})
        if kind in ('table', 'retention'):
            visualization = {'table.pivot': False}
        payload = {'name': definition['title'], 'description': DASHBOARDS[definition['dashboard']]['description'],
                   'collection_id': collection['id'], 'display': display, 'visualization_settings': visualization,
                   'dataset_query': {'database': databases[definition['source']]['id'], 'type': 'native',
                                     'native': {'query': sql_for(definition), 'template-tags': {}}}}
        match = next((row for row in existing_cards if row['name'] == definition['title'] and row.get('collection_id') == collection['id']), None)
        card = client.call(f"/api/card/{match['id']}" if match else '/api/card', payload, method='PUT' if match else 'POST')
        cards.append((definition, card))
    existing_dashboards = client.call('/api/dashboard')
    dashboards = []
    for index, definition in enumerate(DASHBOARDS):
        match = next((row for row in existing_dashboards if row['name'] == definition['name'] and row.get('collection_id') == collection['id']), None)
        dashboard = match or client.call('/api/dashboard', {'name': definition['name'], 'description': definition['description'], 'collection_id': collection['id'], 'parameters': []})
        current = client.call(f"/api/dashboard/{dashboard['id']}")
        previous = {row['card_id']: row['id'] for row in current.get('dashcards', []) if row.get('card_id')}
        dashcards, row, col, current_height = [], 0, 0, 0
        for d, card in cards:
            if d['dashboard'] != index:
                continue
            width, height = ((8, 3) if d['kind'] == 'scalar' else (24, 9) if d['kind'] == 'retention' else (12, 8))
            if col + width > 24:
                row, col, current_height = row + current_height, 0, 0
            dashcards.append({'id': previous.get(card['id'], -len(dashcards)-1), 'card_id': card['id'],
                              'row': row, 'col': col, 'size_x': width, 'size_y': height, 'parameter_mappings': [], 'visualization_settings': {}})
            col, current_height = col + width, max(current_height, height)
        client.call(f"/api/dashboard/{dashboard['id']}", {'dashcards': dashcards}, method='PUT')
        dashboards.append({'id': dashboard['id'], 'name': definition['name']})
    manifest = {'databases': [{'id': row['id'], 'name': row['name']} for row in databases.values()], 'dashboards': dashboards,
                'cards': [{'id': row['id'], 'key': d['key'], 'name': row['name']} for d, row in cards]}
    (FIXTURES/'metabase.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f'Metabase configured: {len(databases)} sources, {len(cards)} cards, {len(dashboards)} dashboards')


if __name__ == '__main__':
    main()
