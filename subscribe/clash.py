# -*- coding: utf-8 -*-

import json
import os
import subprocess
import time
import urllib.request

import utils
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def check(proxy, api_url, timeout, test_url, delay, strict=False):
    """Check a single proxy via clash API"""
    if not proxy or not api_url:
        return False
    name = proxy.get("name", "")
    if not name:
        return False
    
    try:
        # URL encode the proxy name for the API call
        import urllib.parse
        encoded_name = urllib.parse.quote(name, safe="")
        url = f"{api_url}/proxies/{encoded_name}/delay?url={test_url}&timeout={timeout * 1000}"
        
        req = urllib.request.Request(url)
        response = urllib.request.urlopen(req, timeout=timeout + 5)
        if response.getcode() == 200:
            result = json.loads(response.read().decode())
            delay = result.get("delay", 0)
            return 0 < delay < 99999
        return False
    except Exception:
        return False


def generate_config(proxies, workspace):
    """Generate clash config file"""
    if not proxies or not workspace:
        return None
    
    config = {
        "port": 7890,
        "socks-port": 7891,
        "log-level": "silent",
        "allow-lan": False,
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "🚀 节点选择",
                "type": "select",
                "proxies": [p["name"] for p in proxies]
            }
        ],
        "rules": ["MATCH,🚀 节点选择"]
    }
    
    filepath = os.path.join(workspace, "config.yaml")
    utils.write_file(filepath, json.dumps(config, ensure_ascii=False))
    return filepath


def start_clash(bin_path, workspace, config_path):
    """Start clash process"""
    if not os.path.exists(bin_path):
        logger.error(f"clash binary not found: {bin_path}")
        return None
    
    utils.chmod(bin_path)
    try:
        proc = subprocess.Popen(
            [bin_path, "-d", workspace, "-f", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        return proc
    except Exception as e:
        logger.error(f"failed to start clash: {e}")
        return None
