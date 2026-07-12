# -*- coding: utf-8 -*-

import base64
import json
import os
import re
import urllib.parse
import urllib.request

import utils
import yaml
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
        cookie, authorization = "", ""
        if not self.sub:
            logger.info(f"no subscription url for {self.name}, trying auto register...")
            return cookie, authorization
        content = utils.http_get(url=self.sub, retry=retry, timeout=10)
        if not content:
            logger.error(f"failed to fetch subscription: {self.sub}")
        return cookie, authorization
    
    def parse(self, cookie="", auth="", retry=3, rate=2.5, bin_name="", disable_insecure=False, ignore_exclude=True, chatgpt=None, special_protocols=False):
        proxies = []
        if not self.sub:
            return proxies
        
        content = utils.http_get(url=self.sub, retry=retry, timeout=15)
        if not content:
            return proxies
        
        # Try 1: YAML format (Clash config with proxies:)
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and "proxies" in data:
                for p in data["proxies"]:
                    if isinstance(p, dict) and "name" in p and "server" in p:
                        p["liveness"] = True
                        proxies.append(p)
                if proxies:
                    logger.info(f"  parsed {len(proxies)} proxies from YAML format")
                    return proxies
        except:
            pass
        
        # Try 2: base64 encoded subscription links (vmess:// trojan:// ss://)
        full_content = content.strip()
        # Check if it's base64
        try:
            decoded = base64.b64decode(full_content + "=" * (4 - len(full_content) % 4 if len(full_content) % 4 else 0)).decode("utf-8")
            lines = decoded.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("vmess://"):
                    p = self._parse_vmess(line)
                    if p: proxies.append(p)
                elif line.startswith("trojan://"):
                    p = self._parse_trojan(line)
                    if p: proxies.append(p)
                elif line.startswith("ss://"):
                    p = self._parse_ss(line)
                    if p: proxies.append(p)
            if proxies:
                logger.info(f"  parsed {len(proxies)} proxies from base64 subscription")
                return proxies
        except:
            pass
        
        # Try 3: direct links in plain text
        lines = full_content.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("vmess://"):
                p = self._parse_vmess(line)
                if p: proxies.append(p)
            elif line.startswith("trojan://"):
                p = self._parse_trojan(line)
                if p: proxies.append(p)
            elif line.startswith("ss://"):
                p = self._parse_ss(line)
                if p: proxies.append(p)
        
        logger.info(f"  parsed {len(proxies)} proxies from text format")
        return proxies
    
    def _parse_vmess(self, link):
        try:
            data = link.replace("vmess://", "")
            decoded = base64.b64decode(data).decode("utf-8")
            config = json.loads(decoded)
            return {
                "name": config.get("ps", "VMess"), "type": "vmess",
                "server": config.get("add", ""), "port": config.get("port", 443),
                "uuid": config.get("id", ""), "alterId": config.get("aid", 0),
                "cipher": "auto", "network": config.get("net", "tcp"),
                "tls": config.get("tls", "") == "tls",
                "ws-opts": {"path": config.get("path", ""), "headers": {"Host": config.get("host", "")}},
                "liveness": True,
            }
        except: return None
    
    def _parse_trojan(self, link):
        try:
            parsed = urllib.parse.urlparse(link)
            return {"name": urllib.parse.unquote(parsed.fragment or "Trojan"), "type": "trojan",
                    "server": parsed.hostname or "", "port": parsed.port or 443,
                    "password": parsed.password or "", "liveness": True}
        except: return None
    
    def _parse_ss(self, link):
        try:
            data = link.replace("ss://", "")
            name = "SS"
            if "#" in data:
                data, name = data.split("#", 1)
                name = urllib.parse.unquote(name)
            decoded = base64.b64decode(data + "==").decode("utf-8")
            method, rest = decoded.split(":", 1)
            password, server_port = rest.split("@", 1)
            server, port_str = server_port.split(":", 1)
            return {"name": name, "type": "ss", "server": server, "port": int(port_str),
                    "cipher": method, "password": password, "liveness": True}
        except: return None
