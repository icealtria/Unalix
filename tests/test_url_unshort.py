import http.server
import multiprocessing

import unalix

hostname = "127.2.0.1"
port = 56885

base_url = f"http://{hostname}:{port}"

class Server(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200)
        elif self.path == "/redirect-to-tracking":
            self.send_response(301)
            self.send_header("Location", f"http://{hostname}:{port}/ok?utm_source=127.0.0.1")
        elif self.path == "/absolute-redirect":
            self.send_response(301)
            self.send_header("Location", f"http://{hostname}:{port}/redirect-to-tracking")
        elif self.path == "/relative-redirect":
            self.send_response(301)
            self.send_header("Location", "ok")
        elif self.path == "/root-redirect":
            self.send_response(301)
            self.send_header("Location", "/redirect-to-tracking")
        elif self.path == "/i-dont-know-its-name-redirect":
            self.send_response(301)
            self.send_header("Location", f"//{hostname}:{port}/redirect-to-tracking")

        self.end_headers()

server = http.server.HTTPServer((hostname, port), Server)

process = multiprocessing.Process(target=server.serve_forever)
process.start()

def test_unshort():

    unmodified_url = f"{base_url}/absolute-redirect"

    assert unalix.unshort_url(unmodified_url) == f"{base_url}/ok"

    unmodified_url = f"{base_url}/relative-redirect"

    assert unalix.unshort_url(unmodified_url) == f"{base_url}/ok"

    unmodified_url = f"{base_url}/root-redirect"

    assert unalix.unshort_url(unmodified_url) == f"{base_url}/ok"

    unmodified_url = f"{base_url}/i-dont-know-its-name-redirect"

    assert unalix.unshort_url(unmodified_url) == f"{base_url}/ok"

    process.kill()
    server.server_close()
