# -*- coding: utf-8 -*-

import os
import re
from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    if not url:
        return False
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ["http", "https", "ss", "ssr", "vmess", "trojan", "vless"]
    except:
        return False


def isurl(url: str) -> bool:
    return is_valid_url(url)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    url_pattern = re.compile(r'(?:(?:https?|ss|ssr|vmess|trojan|vless)://)[^\s<>\"\']+')
    return list(set(url_pattern.findall(text)))


def is_subscription(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ["http", "https"]:
        return False
    sub_patterns = [r'/sub', r'/subscribe', r'/link', r'/api/v1', r'/s/']
    return any(re.search(p, parsed.path, re.I) for p in sub_patterns)
