"""Idempotently provision the demo's Superset datasets, charts and dashboards."""
import json
import os
from pathlib import Path

from superset.app import create_app
from superset import db, security_manager
from dashboards import DATABASES, DASHBOARDS, CHARTS


def main():
    app = create_app()
    with app.app_context():
        from superset.models.core import Database
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.slice import Slice
        from superset.models.dashboard import Dashboard
        admin = security_manager.find_user(username='admin')
        if admin is None:
            admin = security_manager.add_user(username='admin', first_name='Demo', last_name='Admin',
                                              email=os.environ['ADMIN_EMAIL'], role=security_manager.find_role('Admin'),
                                              password=os.environ['ADMIN_PASSWORD'])
            if not admin:
                raise RuntimeError('Could not create the Superset demo administrator')
        databases, datasets, charts, dashboard_rows = {}, {}, [], []
        for key, (name, schema) in DATABASES.items():
            database = db.session.query(Database).filter_by(database_name=name).one_or_none()
            if database is None:
                database = Database(database_name=name)
                db.session.add(database)
            password = os.environ['READER_PASSWORD']
            database.sqlalchemy_uri = (f'mysql+pymysql://demo_reader:{password}@mysql:3306/{schema}?charset=utf8mb4' if key == 'mysql'
                                       else f'clickhousedb://demo_reader:{password}@clickhouse:8123/{schema}')
            database.expose_in_sqllab = True
            database.allow_dml = False
            db.session.commit()
            databases[key] = database
        for definition in CHARTS:
            key = (definition['source'], definition['table'])
            if key not in datasets:
                database = databases[key[0]]
                schema = DATABASES[key[0]][1]
                dataset = db.session.query(SqlaTable).filter_by(database_id=database.id, table_name=key[1], schema=schema).one_or_none()
                if dataset is None:
                    dataset = SqlaTable(table_name=key[1], schema=schema, database=database, owners=[admin])
                    db.session.add(dataset)
                    db.session.commit()
                dataset.fetch_metadata()
                db.session.commit()
                datasets[key] = dataset
            dataset = datasets[key]
            metric = {'expressionType': 'SQL', 'sqlExpression': definition['metric'], 'label': definition['label'], 'optionName': 'metric_' + definition['key']}
            kind = definition['kind']
            viz = {'scalar': 'big_number_total', 'line': 'echarts_timeseries_line', 'bar': 'echarts_timeseries_bar', 'pie': 'pie', 'table': 'table', 'funnel': 'funnel', 'retention': 'heatmap_v2'}[kind]
            dimensions = definition.get('dimensions', [])
            params = dict(datasource=f'{dataset.id}__table', viz_type=viz, adhoc_filters=[], time_range='No filter',
                          row_limit=definition.get('limit', 1000), color_scheme='supersetColors', show_legend=True,
                          number_format='SMART_NUMBER', y_axis_format='SMART_NUMBER', rich_tooltip=True,
                          extra_form_data={}, annotation_layers=[])
            if kind == 'scalar':
                params.update(metric=metric, header_font_size=0.4, subheader_font_size=0.15, subheader='120 天模拟数据')
            elif kind in ('line', 'bar'):
                params.update(x_axis=dimensions[0], metrics=[metric], groupby=[], x_axis_sort_asc=True,
                              x_axis_time_format='smart_date', time_grain_sqla='P1D', seriesType='line' if kind == 'line' else 'bar',
                              x_axis_sort_series='name', x_axis_sort_series_ascending=True, legendType='scroll', legendOrientation='top',
                              show_empty_columns=True, only_total=True, truncateXAxis=True)
            elif kind == 'retention':
                params.update(x_axis=dimensions[0], groupby=dimensions[1], metric=metric, normalize_across='heatmap',
                              linear_color_scheme='superset_seq_1', show_values=True, show_percentage=False,
                              show_legend=True, value_bounds=[0, 100], sort_x_axis='alpha_asc', sort_y_axis='alpha_asc',
                              x_axis_time_format='smart_date', y_axis_format='.1f', xscale_interval=-1, yscale_interval=-1)
            elif kind in ('pie', 'funnel'):
                params.update(groupby=dimensions, metric=metric, show_labels=True, sort_by_metric=True,
                              percent_calculation_type='first_step', show_tooltip_labels=True, tooltip_label_type=5,
                              legendOrientation='top', legendType='scroll', number_format='SMART_NUMBER')
            else:
                params.update(groupby=dimensions, metrics=[metric], query_mode='aggregate', order_desc=True,
                              include_search=True, page_length=20, table_timestamp_format='smart_date')
            query = dict(columns=dimensions, metrics=[metric], filters=[], time_range='No filter',
                         extras={'having': '', 'where': ''}, row_limit=definition.get('limit', 1000),
                         order_desc=True, is_timeseries=False, url_params={}, custom_params={}, custom_form_data={})
            query['orderby'] = [[dimensions[0], True]] if kind in ('line', 'retention') else [[metric, False]]
            if not dimensions:
                query['orderby'] = []
            context = dict(datasource={'id': dataset.id, 'type': 'table'}, force=False, queries=[query],
                           form_data=params, result_format='json', result_type='full')
            chart = db.session.query(Slice).filter_by(slice_name=definition['title']).one_or_none()
            if chart is None:
                chart = Slice(slice_name=definition['title'], owners=[admin])
                db.session.add(chart)
            chart.datasource_id, chart.datasource_type, chart.datasource_name = dataset.id, 'table', dataset.table_name
            chart.viz_type, chart.params, chart.query_context = viz, json.dumps(params, ensure_ascii=False), json.dumps(context, ensure_ascii=False)
            chart.description = DASHBOARDS[definition['dashboard']]['description']
            db.session.commit()
            charts.append((definition, chart, context))
        for index, definition in enumerate(DASHBOARDS):
            dashboard = db.session.query(Dashboard).filter_by(slug=definition['slug']).one_or_none()
            if dashboard is None:
                dashboard = Dashboard(slug=definition['slug'], owners=[admin])
                db.session.add(dashboard)
            dashboard.dashboard_title = definition['name']
            dashboard.published = True
            selected = [(d, c) for d, c, _ in charts if d['dashboard'] == index]
            dashboard.slices = [c for _, c in selected]
            layout = {'DASHBOARD_VERSION_KEY': 'v2',
                      'ROOT_ID': {'type': 'ROOT', 'id': 'ROOT_ID', 'children': ['GRID_ID']},
                      'GRID_ID': {'type': 'GRID', 'id': 'GRID_ID', 'children': [], 'parents': ['ROOT_ID']}}
            row_index, used = 0, 0
            for d, chart in selected:
                width = 4 if d['kind'] == 'scalar' else (12 if d['kind'] == 'retention' else 6)
                if used + width > 12:
                    row_index += 1
                    used = 0
                row_id = f'ROW-{row_index}'
                if row_id not in layout:
                    layout['GRID_ID']['children'].append(row_id)
                    layout[row_id] = {'id': row_id, 'type': 'ROW', 'children': [], 'parents': ['ROOT_ID', 'GRID_ID'], 'meta': {'background': 'BACKGROUND_TRANSPARENT'}}
                chart_id = f'CHART-{chart.id}'
                layout[row_id]['children'].append(chart_id)
                layout[chart_id] = {'id': chart_id, 'type': 'CHART', 'children': [], 'parents': ['ROOT_ID', 'GRID_ID', row_id],
                                    'meta': {'chartId': chart.id, 'uuid': str(chart.uuid), 'sliceName': chart.slice_name,
                                             'width': width, 'height': 18 if d['kind'] == 'scalar' else 55}}
                used += width
            dashboard.position_json = json.dumps(layout, ensure_ascii=False)
            dashboard.json_metadata = json.dumps({'color_scheme': 'supersetColors', 'refresh_frequency': 0, 'cross_filters_enabled': True})
            db.session.commit()
            dashboard_rows.append({'id': dashboard.id, 'slug': definition['slug'], 'name': definition['name']})
        manifest = {'databases': [{'id': d.id, 'name': d.database_name} for d in databases.values()],
                    'dashboards': dashboard_rows,
                    'charts': [{'id': c.id, 'key': d['key'], 'title': c.slice_name, 'query_context': context} for d, c, context in charts]}
        Path('/app/superset_home/demo-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f'Superset configured: {len(databases)} sources, {len(charts)} charts, {len(dashboard_rows)} dashboards')


if __name__ == '__main__':
    main()
