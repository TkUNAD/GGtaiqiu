"""出站 HTTPS：云托管/Docker 镜像可能缺少系统 CA，依次尝试多种证书源。"""
import os
from typing import Any, List, Union

import requests

CaVerify = Union[bool, str]


def _ca_bundle_paths() -> List[CaVerify]:
    paths: List[CaVerify] = []
    for env_key in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        p = (os.environ.get(env_key) or "").strip()
        if p and os.path.isfile(p):
            paths.append(p)
    try:
        import certifi

        paths.append(certifi.where())
    except ImportError:
        pass
    for system_ca in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ):
        if os.path.isfile(system_ca):
            paths.append(system_ca)
    paths.append(True)

    seen = set()
    out: List[CaVerify] = []
    for item in paths:
        key = item if item is True else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _request(method: str, url: str, **kwargs: Any):
    verify = kwargs.pop("verify", None)
    if verify is not None:
        return requests.request(method, url, verify=verify, **kwargs)

    last_err = None
    for bundle in _ca_bundle_paths():
        try:
            return requests.request(method, url, verify=bundle, **kwargs)
        except requests.exceptions.SSLError as e:
            last_err = e
    if last_err:
        raise last_err
    return requests.request(method, url, **kwargs)


def get(url: str, **kwargs: Any):
    return _request("GET", url, **kwargs)


def post(url: str, **kwargs: Any):
    return _request("POST", url, **kwargs)
