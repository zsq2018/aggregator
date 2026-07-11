# -*- coding: utf-8 -*-

import base64
import json
import os
import re
import urllib.parse
import urllib.request

import utils
from logger import logger

ANOTHER_API_PREFIX = "/api/v1/client/"


class AirPort:
    def __init__(self, name="", site="", sub="", rename="", exclude="", include="", liveness=True, coupon="", api_prefix="/api/v1/"):
        self.name = name
        self.site = site
        self.sub = sub
        self.rename = rename
        self.exclude = exclude
        self.include = include
        self.liveness = liveness
        self.coupon = coupon
        self.api_prefix = api_prefix
        self.registed = False
        self.ref = site or sub or name
    
    def get_subscribe(self, retry=3, rigid=True, chuck=False, invite_code=""):
        """Get subscription content"""
        cookie, authorization = "", ""
        
        if not self.sub:
            logger.info(f"no subscription url for {self.name}, trying auto register...")
            return cookie, authorization
        
        content = utils.http_get(url=self.sub, retry=retry, timeout=10)
        if not content:
            logger.error(f"failed to fetch subscription: {self.sub}")
        
        return cookie, authorization
    
    def parse(self, cookie="", auth="", retry=3, rate=2.5, bin_name="", disable_insecure=False, ignore_exclude=True, chatgpt=None, special_protocols=False):
        """Parse subscription and return proxies"""
        proxies = []
        
        if not self.sub:
            return proxies
        
        content = utils.http_get(url=self.sub, retry=retry, timeout=15)
        if not content:
            return proxies
        
        # Try base64 decode
        try:
            decoded = base64.b64decode(content).decode("utf-8")
            lines = decoded.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("vmess://"):
                    proxy = self._parse_vmess(line)
                    if proxy:
                        proxies.append(proxy)
                elif line.startswith("trojan://"):
                    proxy = self._parse_trojan(line)
                    if proxy:
                        proxies.append(proxy)
                elif line.startswith("ss://"):
                    proxy = self._parse_ss(line)
                    if proxy:
                        proxies.append(proxy)
        except:
            pass
        
        return proxies
    
    def _parse_vmess(self, link):
        try:
            data = link.replace("vmess://", "")
            decoded = base64.b64decode(data).decode("utf-8")
            config = json.loads(decoded)
            return {
                "name": config.get("ps", "VMess"),
                "type": "vmess",
                "server": config.get("add", ""),
                "port": config.get("port", 443),
                "uuid": config.get("id", ""),
                "alterId": config.get("aid", 0),
                "cipher": "auto",
                "network": config.get("net", "tcp"),
                "tls": config.get("tls", "") == "tls",
                "ws-opts": {"path": config.get("path", ""), "headers": {"Host": config.get("host", "")}} if config.get("net") == "ws" else {},
                "liveness": True,
            }
        except:
            return None
    
    def _parse_trojan(self, link):
        try:
            parsed = urllib.parse.urlparse(link)
            password = parsed.password or ""
            server = parsed.hostname or ""
            port = parsed.port or 443
            name = urllib.parse.unquote(parsed.fragment or "Trojan")
            return {"name": name, "type": "trojan", "server": server, "port": port, "password": password, "liveness": True}
        except:
            return None
    
    def _parse_ss(self, link):
        try:
            data = link.replace("ss://", "")
            if "#" in data:
                data, name = data.split("#", 1)
                name = urllib.parse.unquote(name)
            else:
                name = "SS"
            decoded = base64.b64decode(data + "==").decode("utf-8")
            method, rest = decoded.split(":", 1)
            password, server_port = rest.split("@", 1)
            server, port_str = server_port.split(":", 1)
            port = int(port_str)
            return {"name": name, "type": "ss", "server": server, "port": port, "cipher": method, "password": password, "liveness": True}
        except:
            return None
