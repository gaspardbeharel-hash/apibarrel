"""
Local API proxy for api_rotator.

Run this script, then point another project at the local proxy URL instead of
the real API base URL. The proxy forwards requests to the real API and rotates
through keys from api_keys.txt when the active key is rate limited.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import urlsplit

import requests
from api_rotator import (
    DEFAULT_KEYS_FILE,
    DEFAULT_TIMEOUT,
    AllKeysRateLimitedError,
    ApiRotator,
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

IGNORED_REQUEST_HEADERS = {
    "accept-encoding",
    "authorization",
    "content-length",
    "host",
}


class ProxyHandler(BaseHTTPRequestHandler):
    target_base_url: ClassVar[str]
    rotator: ClassVar[ApiRotator]
    timeout: ClassVar[int]

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._handle_request()

    def do_POST(self) -> None:  # noqa: N802
        self._handle_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_request()

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle_request()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_request()

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_request()

    def _handle_request(self) -> None:
        if self.path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        upstream_url = self._build_upstream_url(self.path)
        headers = self._forward_headers()
        body = self._read_body()

        try:
            response = self.rotator.request(
                upstream_url,
                method=self.command,
                headers=headers,
                data=body,
                timeout=self.timeout,
            )
        except AllKeysRateLimitedError as exc:
            self._send_json(429, {"error": str(exc)})
            return
        except requests.RequestException as exc:
            self._send_json(502, {"error": f"Upstream request failed: {exc}"})
            return

        self.send_response(response.status_code)
        for name, value in response.headers.items():
            header_name = name.lower()
            if header_name not in HOP_BY_HOP_HEADERS:
                self.send_header(name, value)
        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(response.content)

        self.log_message(
            "%s %s -> %s",
            self.command,
            self.path,
            response.status_code,
        )

    def _build_upstream_url(self, proxy_path: str) -> str:
        parsed = urlsplit(proxy_path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("Absolute proxy URLs are not supported")

        return self.target_base_url.rstrip("/") + proxy_path

    def _forward_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            header_name = name.lower()
            if (
                header_name in HOP_BY_HOP_HEADERS
                or header_name in IGNORED_REQUEST_HEADERS
            ):
                continue
            headers[name] = value
        return headers

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length")
        if length is None:
            return None

        try:
            size = int(length)
        except ValueError:
            return None

        if size <= 0:
            return None

        return self.rfile.read(size)

    def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - matches base API
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), format % args)
        )


def parse_listen_address(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("Use HOST:PORT, for example 127.0.0.1:8080")

    host, port_text = value.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("PORT must be an integer") from exc

    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("PORT must be between 1 and 65535")

    return host, port


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a local API proxy that rotates API keys."
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("API_PROXY_TARGET"),
        required=True,
        help="Real API base URL to forward requests to, for example https://api.example.com/v1",
    )
    parser.add_argument(
        "--listen",
        default=os.environ.get("API_PROXY_LISTEN", "127.0.0.1:8080"),
        help="Local address to listen on, as HOST:PORT",
    )
    parser.add_argument(
        "--keys-file",
        default=os.environ.get("API_KEYS_FILE", DEFAULT_KEYS_FILE),
        help="Text file containing one API key per line",
    )
    parser.add_argument(
        "--key-header",
        default=os.environ.get("API_KEY_HEADER", "Authorization"),
        help="Header name used for the API key",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("API_PROXY_TIMEOUT", DEFAULT_TIMEOUT)),
        help="Request timeout in seconds",
    )

    args = parser.parse_args()
    host, port = parse_listen_address(args.listen)

    ProxyHandler.target_base_url = args.target
    ProxyHandler.rotator = ApiRotator(
        keys_file=args.keys_file,
        key_header=args.key_header,
        timeout=args.timeout,
    )
    ProxyHandler.timeout = args.timeout

    server = ThreadingHTTPServer((host, port), ProxyHandler)
    print(f"API rotator proxy listening on http://{host}:{port}")
    print(f"Forwarding to {args.target}")
    print(f"Using keys from {args.keys_file}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping proxy...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
