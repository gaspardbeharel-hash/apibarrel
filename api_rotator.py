"""
API key rotator.

Loads API keys from a text file and retries requests with the next key when the
current key is rate limited by the remote API.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

DEFAULT_KEYS_FILE = "api_keys.txt"
DEFAULT_TIMEOUT = 30


class NoApiKeyError(RuntimeError):
    """Raised when no API keys are available."""


class AllKeysRateLimitedError(RuntimeError):
    """Raised when every available key was rate limited."""


def load_api_keys(path: str | os.PathLike[str] = DEFAULT_KEYS_FILE) -> list[str]:
    """Load API keys from a text file, one key per line.

    Empty lines and lines starting with ``#`` are ignored.
    Whitespace around each key is stripped.
    """

    keys_path = Path(path)
    if not keys_path.exists():
        raise FileNotFoundError(f"API keys file not found: {keys_path}")

    keys: list[str] = []
    for raw_line in keys_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keys.append(line)

    if not keys:
        raise NoApiKeyError(f"No API keys found in {keys_path}")

    return keys


@dataclass
class ApiRotator:
    """Rotate API keys for requests.

    Args:
        keys_file: Path to a text file containing one API key per line.
        key_header: Header name used to send the selected API key.
        timeout: Default request timeout in seconds.
    """

    keys_file: str | os.PathLike[str] = DEFAULT_KEYS_FILE
    key_header: str = "Authorization"
    timeout: int = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        self.keys = load_api_keys(self.keys_file)
        self.current_index = 0

    def _key_headers(self, key: str) -> dict[str, str]:
        """Return headers for the selected key."""

        if self.key_header.lower() == "authorization":
            return {self.key_header: f"Bearer {key}"}

        return {self.key_header: key}

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: int | None = None,
        rate_limit_status_codes: Iterable[int] = (429,),
        **kwargs: Any,
    ) -> requests.Response:
        """Send a request while rotating through API keys on rate-limit errors.

        The first key is tried, then the next key is used if the API returns a
        rate-limit status code. This continues until the request succeeds or all
        keys have been tried.
        """

        if not self.keys:
            raise NoApiKeyError("No API keys are configured")

        request_headers = dict(headers or {})
        request_timeout = timeout or self.timeout
        rate_limit_codes = set(rate_limit_status_codes)
        attempts: list[int] = []

        for _ in range(len(self.keys)):
            key = self.keys[self.current_index]
            attempts.append(self.current_index)

            request_headers.update(self._key_headers(key))

            response = requests.request(
                method=method.upper(),
                url=url,
                headers=request_headers,
                json=json_body,
                data=data,
                timeout=request_timeout,
                **kwargs,
            )

            if response.status_code not in rate_limit_codes:
                return response

            # Move to the next key for the next request attempt.
            self.current_index = (self.current_index + 1) % len(self.keys)

        raise AllKeysRateLimitedError(
            f"All {len(self.keys)} API keys were rate limited. Tried indexes: {attempts}"
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request(url, method="GET", **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request(url, method="POST", **kwargs)


def request(
    url: str,
    *,
    keys_file: str | os.PathLike[str] = DEFAULT_KEYS_FILE,
    key_header: str = "Authorization",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int | None = None,
    rate_limit_status_codes: Iterable[int] = (429,),
    **kwargs: Any,
) -> requests.Response:
    """Convenience function that creates a rotator and sends one request."""

    rotator = ApiRotator(
        keys_file=keys_file,
        key_header=key_header,
        timeout=timeout or DEFAULT_TIMEOUT,
    )
    return rotator.request(
        url,
        method=method,
        headers=headers,
        json_body=json_body,
        data=data,
        timeout=timeout,
        rate_limit_status_codes=rate_limit_status_codes,
        **kwargs,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate API keys from a text file.")
    parser.add_argument("url", help="API URL to request")
    parser.add_argument(
        "--keys-file",
        default=DEFAULT_KEYS_FILE,
        help="Path to the API keys text file",
    )
    parser.add_argument(
        "--key-header",
        default="Authorization",
        help="Header name used for the API key",
    )
    parser.add_argument(
        "--method",
        default="GET",
        choices=["GET", "POST", "PUT", "PATCH", "DELETE"],
        help="HTTP method to use",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--print-status",
        action="store_true",
        help="Print only the HTTP status code",
    )

    args = parser.parse_args()

    rotator = ApiRotator(
        keys_file=args.keys_file,
        key_header=args.key_header,
        timeout=args.timeout,
    )

    try:
        response = rotator.request(args.url, method=args.method)
    except (FileNotFoundError, NoApiKeyError, AllKeysRateLimitedError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.print_status:
        print(response.status_code)
    else:
        print(response.text)


if __name__ == "__main__":
    main()
