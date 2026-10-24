"""Verified proxy transport: never inherit ambient proxy/bypass variables."""

import ipaddress
import time
from dataclasses import dataclass

import requests

from psiphon import config


@dataclass(frozen=True)
class Measurement:
    mbps: float
    bytes_received: int
    elapsed_s: float
    first_byte_s: float


def session(proxy: str | None = None) -> requests.Session:
    client = requests.Session()
    client.trust_env = False
    if proxy is not None:
        client.proxies = {"http": proxy, "https": proxy}
    return client


def public_ip(proxy: str | None = None, timeout: float = 5) -> str:
    errors = []
    with session(proxy) as client:
        for url in config.IP_URLS:
            try:
                response = client.get(url, timeout=(timeout, timeout))
                response.raise_for_status()
                return str(ipaddress.ip_address(response.text.strip()))
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{url}: {exc}")
    raise ConnectionError("IP verification failed: " + "; ".join(errors))


def download(seconds: float, proxy: str | None = None) -> Measurement:
    if not 1 <= seconds <= 60:
        raise ValueError("Measurement duration must be between 1 and 60 seconds")
    started = time.monotonic()
    first_byte = None
    total = 0
    with (
        session(proxy) as client,
        client.get(
            config.SPEEDTEST_URL,
            stream=True,
            timeout=(5, min(seconds, 5)),
            headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"},
        ) as response,
    ):
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=16_384):
            if chunk:
                first_byte = first_byte or time.monotonic() - started
                total += len(chunk)
            if time.monotonic() - started >= seconds:
                break
    elapsed = max(time.monotonic() - started, 0.001)
    if not total:
        raise ConnectionError("No payload received; throughput is unmeasured")
    return Measurement(
        total * 8 / elapsed / 1_000_000, total, elapsed, first_byte or elapsed
    )


def geo(address: str, proxy: str | None = None) -> dict:
    address = str(ipaddress.ip_address(address))
    with session(proxy) as client:
        response = client.get(config.GEO_URL + address, timeout=(5, 5))
        response.raise_for_status()
        data = response.json()
        if data.get("success") is not True:
            raise ConnectionError(
                f"GeoIP lookup failed: {data.get('message', 'unknown')}"
            )
        return {key: data.get(key) for key in ("country", "country_code", "city")}


def upload(seconds: float, proxy: str | None = None) -> Measurement:
    """Bounded payload upload; only a successful HTTP response yields a result.

    The configured duration is a send budget, not an absolute HTTP wall deadline.
    The response timeout is bounded separately; setup/response time is included.
    """
    if not 1 <= seconds <= 60:
        raise ValueError("Measurement duration must be between 1 and 60 seconds")
    started = time.monotonic()
    total = 0
    first_byte = None

    def chunks():
        nonlocal total, first_byte
        # Limit data use even on an exceptionally fast link.
        while time.monotonic() - started < seconds and total < 40_000_000:
            chunk = b"\0" * min(65536, 40_000_000 - total)
            yield chunk
            first_byte = first_byte or time.monotonic() - started
            total += len(chunk)

    with session(proxy) as client:
        response = client.post(
            config.UPLOAD_URL,
            data=chunks(),
            timeout=(5, 5),
            headers={"Content-Type": "application/octet-stream"},
        )
        response.raise_for_status()
    elapsed = max(time.monotonic() - started, 0.001)
    if not total:
        raise ConnectionError("No upload payload sent; throughput is unmeasured")
    return Measurement(
        total * 8 / elapsed / 1_000_000, total, elapsed, first_byte or elapsed
    )
