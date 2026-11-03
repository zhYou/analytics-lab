#!/usr/bin/env python3
"""Optional Chromium checks for native Rybbit pages and login."""
import json
import os
from playwright.sync_api import sync_playwright
from common import ROOT, FIXTURES, env


def main():
    settings = env()
    manifest = json.loads((FIXTURES/'rybbit.json').read_text())
    target = ROOT/'screenshots'
    target.mkdir(exist_ok=True)
    report = []
    with sync_playwright() as p:
        options = {'headless': True, 'args': ['--no-sandbox']}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100})
        page = context.new_page()
        errors, failures, expected_external = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def response_check(response):
            if response.status < 400:
                return
            failure = f'{response.status} {response.url.split("?")[0]}'
            # This intentionally fictional hostname has no public favicon.
            if response.status == 404 and response.url == 'https://icons.duckduckgo.com/ip3/demo.analytics.test.ico':
                expected_external.append(failure)
            else:
                failures.append(failure)
        page.on('response', response_check)
        page.goto('http://localhost:3001/login', wait_until='networkidle')
        page.locator('#email').fill(settings['ADMIN_EMAIL'])
        page.locator('#password').fill(settings['ADMIN_PASSWORD'])
        page.locator('button[type="submit"]').click()
        page.wait_for_function("!location.pathname.includes('/login')", timeout=45000)
        for route in ['main', 'events', 'funnels', 'retention', 'users', 'journeys']:
            errors.clear()
            failures.clear()
            expected_external.clear()
            if route == 'main':
                page.goto(f"http://localhost:3001/{manifest['site_id']}/main?wellKnown=all-time",wait_until='networkidle')
            else:
                page.locator(f"a[href^='/{manifest['site_id']}/{route}']").first.click()
                page.wait_for_url(f'**/{route}**', timeout=30000)
                page.wait_for_load_state('networkidle')
            page.wait_for_timeout(3000)
            text = page.locator('body').inner_text()
            page.screenshot(path=str(target/f'rybbit-{route.replace("/", "-")}.png'),full_page=True)
            report.append({'page': route,'url': page.url,'text': text[:7000], 'errors': list(errors), 'http_errors': list(failures), 'expected_external': list(expected_external)})
            print(route,'JS errors:',len(errors),'HTTP errors:',failures,flush=True)
            assert '/login' not in page.url, 'Lost authenticated browser session'
            if route=='funnels':
                assert all(x['name'] in text for x in manifest['funnels']), text[:800]
            if route=='events':
                assert 'feature_used' in text, text[:800]
        # User detail does not consume generic date URL parameters upstream.
        # Exercise the actual user flow; SPA navigation preserves All Time.
        page.locator(f"a[href^='/{manifest['site_id']}/users']").first.click()
        page.wait_for_url('**/users**', timeout=30000)
        page.wait_for_load_state('networkidle')
        errors.clear()
        failures.clear()
        expected_external.clear()
        page.locator(f"a[href^='/{manifest['site_id']}/user/']").first.click()
        page.wait_for_url('**/user/**', timeout=30000)
        page.wait_for_timeout(3000)
        text = page.locator('body').inner_text()
        page.screenshot(path=str(target/'rybbit-user-detail.png'), full_page=True)
        report.append({'page': 'user-detail', 'url': page.url, 'text': text[:7000], 'errors': list(errors),
                       'http_errors': list(failures), 'expected_external': list(expected_external)})
        print('user-detail', 'JS errors:',len(errors),'HTTP errors:',failures,flush=True)
        assert 'All Time' in text, 'User navigation lost the selected reporting period'
        assert 'No sessions found' not in text, 'User detail should show actual sessions'
        browser.close()
    (ROOT/'logs'/'rybbit-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    assert all(not x['errors'] and not x['http_errors'] for x in report), 'See logs/rybbit-browser.json'


if __name__ == '__main__':
    main()
