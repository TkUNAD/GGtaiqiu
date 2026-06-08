"""出站 HTTPS：云托管/Docker 镜像可能缺少系统 CA，统一用 certifi 校验证书。"""
import requests

try:
    import certifi

    VERIFY_SSL = certifi.where()
except ImportError:
    VERIFY_SSL = True


def get(url, **kwargs):
    kwargs.setdefault("verify", VERIFY_SSL)
    return requests.get(url, **kwargs)


def post(url, **kwargs):
    kwargs.setdefault("verify", VERIFY_SSL)
    return requests.post(url, **kwargs)
