# -*- coding: utf-8 -*-

import json
import os
import re

import utils
from logger import logger


def batch_crawl(config, domains, push_conf):
    """Batch crawl from multiple sources"""
    if not config or not config.get("enable", True):
        return []
    
    results = []
    
    # Crawl from telegram
    telegram_conf = config.get("telegram", {})
    if telegram_conf.get("enable", False):
        subs = crawl_telegram(telegram_conf)
        results.extend(subs)
        logger.info(f"[TelegramCrawl] finished crawl from Telegram, found {len(subs)} subscriptions")
    
    # Crawl from github
    github_conf = config.get("github", {})
    if github_conf.get("enable", False):
        subs = crawl_github(github_conf)
        results.extend(subs)
        logger.info(f"[GithubCrawl] finished crawl from Github, found {len(subs)} subscriptions")
    
    return results


def crawl_telegram(config):
    """Crawl subscriptions from telegram channels"""
    if not config:
        return []
    
    subs = []
    users = config.get("users", {})
    pages = config.get("pages", 3)
    
    for username, user_conf in users.items():
        try:
            url = f"https://t.me/s/{username}"
            content = utils.http_get(url=url, retry=2, timeout=10)
            if content:
                # Extract URLs from content
                urls = re.findall(r'https?://[^\s<>"\']+', content)
                for u in urls:
                    if any(k in u.lower() for k in ['subscribe', 'sub', 'token=', 'clash', 'v2ray', 'trojan', 'ss://', 'vmess://']):
                        subs.append(u)
        except Exception as e:
            logger.error(f"failed to crawl telegram channel {username}: {e}")
    
    return list(set(subs))


def crawl_github(config):
    """Crawl subscriptions from GitHub"""
    if not config:
        return []
    
    subs = []
    token = os.environ.get("GH_TOKEN", "")
    
    try:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # Search for subscription URLs in code
        queries = [
            "subscribe?token=&extension=txt",
            "clash&filename=config&extension=yaml",
            "v2ray subscription",
            "https://raw.githubusercontent.com",
        ]
        
        for query in queries:
            try:
                encoded = urllib.parse.quote(query)
                # Use basic search URL
                url = f"https://api.github.com/search/code?q={encoded}+size:<50000&per_page=10"
                # Actually use a simpler approach - search repos
                url = f"https://api.github.com/search/repositories?q=free+proxy+subscription&sort=updated&per_page=10"
                req = urllib.request.Request(url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=10)
                if resp.getcode() == 200:
                    data = json.loads(resp.read().decode())
                    for item in data.get("items", []):
                        repo_url = item.get("html_url", "")
                        if repo_url:
                            subs.append(repo_url + "/raw/master/v2")
                            subs.append(repo_url + "/raw/main/v2")
            except:
                pass
    except Exception as e:
        logger.error(f"github crawl error: {e}")
    
    return list(set(subs))


import urllib.parse
import urllib.request
