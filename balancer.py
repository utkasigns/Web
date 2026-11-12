import http.client
import itertools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

servers = [('localhost', 3001), ('localhost', 3002)]
queue = itertools.cycle(servers)
skip_headers = ('transfer-encoding', 'connection', 'server', 'date')


class Balancer(BaseHTTPRequestHandler):
    def handle_any(self):
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        host, port = next(queue)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else None

        try:
            conn = http.client.HTTPConnection(host, port)
            conn.request(self.command, self.path, body, dict(self.headers))
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
        except OSError:
            self.send_response(502)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('Сервер недоступний'.encode())
            return

        self.send_response(resp.status)
        for key, value in resp.getheaders():
            if key.lower() not in skip_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    do_GET = handle_any
    do_POST = handle_any


ThreadingHTTPServer(('', 8080), Balancer).serve_forever()