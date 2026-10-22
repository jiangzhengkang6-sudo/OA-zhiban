"""Check the frontend image on a private Docker network using synthetic HTTP only."""

import argparse
import json
import subprocess
from uuid import uuid4


BACKEND = r'''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'path': self.path, 'host': self.headers['Host'],
                           'forwarded_proto': self.headers.get('X-Forwarded-Proto')}).encode()
        self.send_response(404 if self.path == '/api/missing' else 200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

HTTPServer(('0.0.0.0', 8001), Handler).serve_forever()
'''

PROBE = r'''
from html.parser import HTMLParser
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def fetch(path, data=None):
    request = Request('http://frontend:8080' + path, data=data)
    with urlopen(request, timeout=5) as response:
        return response.read(), response.headers

for attempt in range(30):
    try:
        health, headers = fetch('/healthz')
        break
    except (URLError, TimeoutError):
        if attempt == 29:
            raise
        time.sleep(1)
assert health == b'ok\n' and headers.get_all('Content-Type') == ['text/plain']
root, _ = fetch('/')
assert b'<div id="app">' in root
assert fetch('/assistant')[0] == root

class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script' and values.get('src'):
            self.paths.append(values['src'])
        if tag == 'link' and values.get('rel') == 'stylesheet':
            self.paths.append(values['href'])

assets = Assets()
assets.feed(root.decode())
assert any(path.endswith('.js') for path in assets.paths)
assert any(path.endswith('.css') for path in assets.paths)
for path in assets.paths:
    assert path.startswith('/assets/')
    body, headers = fetch(path)
    assert body and body != root
    assert ('javascript' if path.endswith('.js') else 'text/css') in headers['Content-Type']
api = json.loads(fetch('/api/m4-smoke?synthetic=1')[0])
assert api == {'path': '/api/m4-smoke?synthetic=1', 'host': 'frontend', 'forwarded_proto': 'http'}
assert fetch('/api/m4-smoke', b'{"synthetic":true}')[0] == b'{"synthetic":true}'
try:
    fetch('/api/missing')
    raise AssertionError('Backend 404 was hidden')
except HTTPError as error:
    assert error.code == 404
print(json.dumps({'health': 'pass', 'spa_routes': 'pass', 'assets': assets.paths,
                  'api_get_query_headers': 'pass', 'api_post': 'pass', 'api_404': 'pass'}))
'''

OUTAGE_PROBE = r'''
from urllib.error import HTTPError
from urllib.request import urlopen
try:
    urlopen('http://frontend:8080/api/m4-smoke', timeout=10)
    raise AssertionError('Backend outage was hidden')
except HTTPError as error:
    assert error.code == 502
with urlopen('http://frontend:8080/healthz', timeout=5) as response:
    assert response.read() == b'ok\n'
print('{"backend_outage_502":"pass","static_health_during_outage":"pass"}')
'''


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Synthetic Docker check failed: ' + result.stderr.strip())
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-image', default='oa-m4-resilience-frontend:local')
    parser.add_argument('--probe-image', default='python:3.12-slim')
    args = parser.parse_args()
    frontend_id = docker('image', 'inspect', '--format', '{{.Id}}', args.frontend_image)
    probe_id = docker('image', 'inspect', '--format', '{{.Id}}', args.probe_image)
    network = 'oa-m4-frontend-' + uuid4().hex[:12]
    created = []
    network_created = False
    try:
        docker('network', 'create', '--internal', '--label', 'oa.m4.synthetic=true', network)
        network_created = True
        for role, image, command in (
            ('backend', probe_id, ['python', '-u', '-c', BACKEND]),
            ('frontend', frontend_id, []),
        ):
            container = docker('create', '--network', network, '--network-alias', role,
                               '--label', 'oa.m4.synthetic=true', image, *command)
            created.append(container)
            docker('start', container)
        def probe(source):
            container = docker('create', '--network', network, '--label',
                               'oa.m4.synthetic=true', probe_id, 'python', '-c', source)
            created.append(container)
            output = docker('start', '-a', container)
            if docker('inspect', '--format', '{{.State.ExitCode}}', container) != '0':
                raise RuntimeError('Synthetic probe failed: ' + docker('logs', container))
            return json.loads(output)

        results = [probe(PROBE)]
        docker('stop', '--time', '2', created[0])
        results.append(probe(OUTAGE_PROBE))
        print(json.dumps({'frontend_image': frontend_id, 'probe_image': probe_id,
                          'network': network, 'checks': results}, indent=2))
    finally:
        # Only IDs returned by this invocation are ever eligible for cleanup.
        failures = []
        for container in reversed(created):
            try:
                docker('rm', '-f', container)
            except RuntimeError as error:
                failures.append(str(error))
        if network_created:
            try:
                docker('network', 'rm', network)
            except RuntimeError as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError('Synthetic resource cleanup failed: ' + '; '.join(failures))


if __name__ == '__main__':
    main()
