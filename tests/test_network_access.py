"""Exercise network authorities and CSRF over a real HTTP connection."""
import http.client
import json
import select
import socket
import socketserver
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import app
from http_api import build_handler


class NetworkAccessTest(unittest.TestCase):
    def setUp(self):
        self.context = dict(vars(app), HOST="0.0.0.0", ALLOWED_HOSTS={"192.168.1.50"})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(self.context))
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, host, origin=None, method="GET", token=None, path="/"):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Host": host}
        if origin is not None:
            headers["Origin"] = origin
        if token is not None:
            headers["X-AX-Token"] = token
        headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body="{}" if method == "POST" else None, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_windows_ip_serves_gui_bootstrap_and_same_origin_post(self):
        host = f"192.168.1.50:{self.port}"
        self.assertEqual(self.request(host)[0], 200)
        status, body = self.request(host, path="/api/bootstrap")
        self.assertEqual(status, 200)
        token = json.loads(body)["token"]
        # Unknown route proves validation passed without mutating any workspace.
        self.assertEqual(self.request(host, f"http://{host}", "POST", token)[0], 404)
        self.assertEqual(self.request(host, f"http://{host}", "POST")[0], 403)

    def test_localhost_still_works(self):
        for name in ("127.0.0.1", "localhost"):
            host = f"{name}:{self.port}"
            self.assertEqual(self.request(host, f"http://{host}")[0], 200)

    def test_unlisted_host_wrong_port_and_cross_origin_are_rejected(self):
        host = f"192.168.1.50:{self.port}"
        for authority in (f"evil.example:{self.port}", f"192.168.1.51:{self.port}",
                          "192.168.1.50:1", f"0.0.0.0:{self.port}"):
            self.assertEqual(self.request(authority)[0], 403)
        for origin in ("null", "https://" + host, "http://evil.example", f"http://localhost:{self.port}"):
            self.assertEqual(self.request(host, origin)[0], 403)
            self.assertEqual(self.request(host, origin, "POST", self.context["CSRF"])[0], 403)

    def test_default_mode_rejects_windows_authority(self):
        self.context.update(HOST="127.0.0.1", ALLOWED_HOSTS=set())
        self.assertEqual(self.request(f"192.168.1.50:{self.port}")[0], 403)

    def test_specific_bind_address_is_allowed(self):
        self.context.update(HOST="192.168.1.51", ALLOWED_HOSTS=set())
        self.assertEqual(self.request(f"192.168.1.51:{self.port}")[0], 200)


class PortForwardingTest(unittest.TestCase):
    def test_tcp_forward_preserves_windows_host_for_gui_and_api(self):
        """Model WindowsIP:port -> WSLIP:same-port using two loopback addresses."""
        context = dict(vars(app), HOST="0.0.0.0", ALLOWED_HOSTS={"10.20.30.40"})
        backend = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(context))
        port = backend.server_port

        class Forwarder(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.create_connection(backend.server_address, timeout=3) as upstream:
                    peers = (self.request, upstream)
                    while True:
                        readable, _, _ = select.select(peers, [], [], 3)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            destination = upstream if source is self.request else self.request
                            destination.sendall(data)

        proxy = socketserver.ThreadingTCPServer(("127.0.0.2", port), Forwarder)
        proxy.daemon_threads = True
        threads = [threading.Thread(target=server.serve_forever, daemon=True)
                   for server in (backend, proxy)]
        for thread in threads:
            thread.start()
        try:
            host = f"10.20.30.40:{port}"
            for path in ("/", "/app.js", "/api/bootstrap"):
                connection = http.client.HTTPConnection("127.0.0.2", port, timeout=3)
                try:
                    connection.request("GET", path, headers={"Host": host})
                    response = connection.getresponse()
                    body = response.read()
                    self.assertEqual(response.status, 200)
                    if path == "/api/bootstrap":
                        token = json.loads(body)["token"]
                finally:
                    connection.close()
            connection = http.client.HTTPConnection("127.0.0.2", port, timeout=3)
            try:
                connection.request("POST", "/api/not-a-route", body="{}", headers={
                    "Host": host, "Origin": f"http://{host}",
                    "Content-Type": "application/json", "X-AX-Token": token,
                })
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 404)  # Passed Host/Origin/CSRF, no writes.
            finally:
                connection.close()
        finally:
            for server in (proxy, backend):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()


class ServerArgumentsTest(unittest.TestCase):
    def test_network_arguments(self):
        with patch.object(app, "ALLOWED_HOSTS", set()):
            args = app.parse_server_args(["--host", "0.0.0.0", "--port", "9000",
                                          "--allow-host", "192.168.1.50", "--allow-host", "dev-pc"])
        self.assertEqual((args.host, args.port, args.allow_host),
                         ("0.0.0.0", 9000, ["192.168.1.50", "dev-pc"]))

    def test_invalid_port_and_host_fail_before_startup(self):
        for args in (["--port", "0"], ["--port", "65536"],
                     ["--allow-host", "*"], ["--allow-host", "http://192.168.1.50:8765"]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                app.parse_server_args(args)
