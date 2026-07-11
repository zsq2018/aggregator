# -*- coding: utf-8 -*-

import json
import os
import urllib.request

import utils
from logger import logger


def check_proxies(proxies, api_url, timeout, test_url, delay):
    """Check proxies via clash API"""
    if not proxies:
        return []
    
    results = []
    for proxy in proxies:
        try:
            import urllib.parse
            name = proxy.get("name", "")
            if not name:
                continue
            encoded = urllib.parse.quote(name, safe="")
            url = f"{api_url}/proxies/{encoded}/delay?url={test_url}&timeout={timeout * 1000}"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=max(timeout + 5, 10))
            if resp.getcode() == 200:
                data = json.loads(resp.read().decode())
                delay_val = data.get("delay", 0)
                if 0 < delay_val < 99999:
                    results.append(name)
        except Exception:
            pass
    
    return results


def locate(proxies):
    """Simple geo-location via API"""
    results = {}
    for proxy in proxies:
        name = proxy.get("name", "")
        server = proxy.get("server", "")
        if name and server:
            try:
                url = f"http://ip-api.com/json/{server}?fields=country,countryCode"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=5)
                if resp.getcode() == 200:
                    data = json.loads(resp.read().decode())
                    country = data.get("country", "")
                    code = data.get("countryCode", "")
                    if country:
                        results[name] = f"{code} {country}"
            except Exception:
                pass
    return results
