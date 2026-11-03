#!/usr/bin/env python3
"""Optional Playwright smoke check; install with uv run --with playwright."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright
from common import ROOT, FIXTURES, env


def main():
    settings = env()
    target = ROOT/'screenshots'
    target.mkdir(exist_ok=True)
    report = []
    with sync_playwright() as playwright:
        options = {'headless': True, 'args': ['--no-sandbox']}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100}, device_scale_factor=1)
        page = context.new_page()
        errors, failures = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: failures.append(f'{response.status} {response.url.split("?")[0]}') if response.status >= 400 else None)
        page.goto('http://localhost:8088/login/', wait_until='networkidle')
        page.locator('#username').fill('admin')
        page.locator('#password').fill(settings['ADMIN_PASSWORD'])
        page.locator('input[type="submit"], button[type="submit"]').click()
        page.wait_for_url('**/superset/welcome/**', timeout=60000)
        for slug in ['business-overview', 'user-analytics']:
            errors.clear()
            failures.clear()
            page.goto(f'http://localhost:8088/superset/dashboard/{slug}/', wait_until='networkidle')
            page.wait_for_selector('.chart-container', timeout=60000)
            page.wait_for_timeout(5000)
            page.screenshot(path=str(target/f'superset-{slug}.png'), full_page=True)
            text = page.locator('body').inner_text()
            report.append({'app': 'superset', 'dashboard': slug, 'charts': page.locator('.chart-container').count(),
                           'errors': list(errors), 'http_errors': list(failures), 'text': text[:5000]})
        context.close()
        context = browser.new_context(viewport={'width': 1600, 'height': 1100}, device_scale_factor=1)
        response = context.request.post('http://localhost:3000/api/session', data={'username': settings['ADMIN_EMAIL'], 'password': settings['ADMIN_PASSWORD']})
        assert response.ok, response.status
        session = response.json()['id']
        context.add_cookies([{'name': 'metabase.SESSION', 'value': session, 'domain': 'localhost', 'path': '/', 'httpOnly': True, 'sameSite': 'Lax'}])
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: failures.append(f'{response.status} {response.url.split("?")[0]}') if response.status >= 400 else None)
        for dashboard in json.loads((FIXTURES/'metabase.json').read_text())['dashboards']:
            errors.clear()
            failures.clear()
            page.goto(f"http://localhost:3000/dashboard/{dashboard['id']}", wait_until='networkidle')
            page.wait_for_selector('[data-testid="dashcard"]', timeout=60000)
            page.wait_for_timeout(5000)
            page.screenshot(path=str(target/f"metabase-{dashboard['id']}.png"), full_page=True)
            text = page.locator('body').inner_text()
            report.append({'app': 'metabase', 'dashboard': dashboard['name'], 'charts': page.locator('[data-testid="dashcard"]').count(),
                           'errors': list(errors), 'http_errors': list(failures), 'text': text[:5000]})
        browser.close()
    (ROOT/'logs'/'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for row in report:
        print(row['app'], row['dashboard'], row['charts'], 'charts;', len(row['errors']), 'JS errors;', row['http_errors'])
    assert all(row['charts'] > 0 and not row['errors'] and not row['http_errors'] for row in report), 'Browser errors; see logs/browser.json'


if __name__ == '__main__':
    main()
