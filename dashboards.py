"""Shared chart definitions; both BI products query the same source views."""
DATABASES = {
    'clickhouse': ('ClickHouse · 业务与行为', 'analytics_demo'),
    'mysql': ('MySQL · 客户与订单', 'analytics_demo'),
    'openobserve': ('OpenObserve · API 聚合副本', 'openobserve_demo'),
}
DASHBOARDS = [
    {'slug': 'business-overview', 'name': '经营总览 · 三数据源', 'description': '120 天模拟业务。净收入仅计 paid 订单；OpenObserve 图表来自其搜索 API 的 ClickHouse 聚合副本。'},
    {'slug': 'user-analytics', 'name': '用户分析 · 漏斗与留存', 'description': '注册 → 激活 → 7 日内支付；按注册周观察 feature_used 活跃留存，仅展示已完成的自然周。'},
]
# Metric SQL expressions work in both ClickHouse and MySQL.
CHARTS = [
    dict(key='revenue', dashboard=0, title='净收入（元） · ClickHouse', source='clickhouse', table='daily_business', kind='scalar', metric='SUM(net_revenue)', label='净收入'),
    dict(key='paid-orders', dashboard=0, title='已支付订单 · ClickHouse', source='clickhouse', table='daily_business', kind='scalar', metric='SUM(paid_orders)', label='支付订单'),
    dict(key='customers', dashboard=0, title='注册用户 · MySQL', source='mysql', table='users', kind='scalar', metric='COUNT(*)', label='注册用户'),
    dict(key='revenue-trend', dashboard=0, title='每日净收入 · ClickHouse', source='clickhouse', table='daily_business', kind='line', dimensions=['day'], metric='SUM(net_revenue)', label='净收入'),
    dict(key='channel-revenue', dashboard=0, title='渠道收入 · ClickHouse', source='clickhouse', table='channel_revenue', kind='bar', dimensions=['channel'], metric='SUM(net_revenue)', label='净收入'),
    dict(key='product-revenue', dashboard=0, title='产品收入 · ClickHouse', source='clickhouse', table='product_revenue', kind='pie', dimensions=['product'], metric='SUM(net_revenue)', label='净收入'),
    dict(key='top-customers', dashboard=0, title='客户收入 TOP 20 · MySQL', source='mysql', table='customer_revenue', kind='table', dimensions=['user_name', 'channel', 'region'], metric='SUM(net_revenue)', label='净收入', limit=20),
    dict(key='observed-events', dashboard=0, title='每日事件量 · OpenObserve API', source='openobserve', table='daily_events', kind='line', dimensions=['day'], metric='SUM(event_count)', label='事件数'),
    dict(key='activity', dashboard=1, title='每日活跃用户 · ClickHouse', source='clickhouse', table='daily_activity', kind='line', dimensions=['day'], metric='SUM(active_users)', label='活跃用户'),
    dict(key='signups', dashboard=1, title='每日新增注册 · ClickHouse', source='clickhouse', table='daily_activity', kind='line', dimensions=['day'], metric='SUM(signups)', label='新增注册'),
    dict(key='funnel', dashboard=1, title='注册 → 激活 → 7 日内支付', source='clickhouse', table='funnel_summary', kind='funnel', dimensions=['stage'], metric='SUM(users)', label='用户数'),
    dict(key='retention', dashboard=1, title='注册周留存（%）', source='clickhouse', table='weekly_retention', kind='retention', dimensions=['week_index', 'cohort_week'], metric='MAX(retention_percent)', label='留存率'),
    dict(key='event-types', dashboard=1, title='行为事件分布 · OpenObserve API', source='openobserve', table='event_types', kind='bar', dimensions=['event_name'], metric='SUM(event_count)', label='事件数'),
]


def sql_for(chart):
    dimensions = chart.get('dimensions', [])
    # Stable ASCII aliases simplify Metabase visualization settings.
    selected = [*dimensions, f"{chart['metric']} AS value"]
    query = f"SELECT {', '.join(selected)} FROM {chart['table']}"
    if dimensions:
        query += ' GROUP BY ' + ', '.join(dimensions)
        order = ', '.join(dimensions) if chart['kind'] in ('line', 'retention') else 'value DESC'
        query += ' ORDER BY ' + order
    return query + f" LIMIT {chart.get('limit', 1000)}"
