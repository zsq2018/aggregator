# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import sys
import urllib.parse

import crawl
import executable
import push
import utils
import workflow
import yaml
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def proxy_to_v2ray_link(proxy):
    """Convert a proxy dict to proper V2Ray subscription link"""
    ptype = proxy.get("type", "")
    name = proxy.get("name", "unknown")
    server = proxy.get("server", "")
    port = proxy.get("port", 443)

    try:
        if ptype == "vmess":
            cfg = {
                "v": "2",
                "ps": name,
                "add": server,
                "port": int(port),
                "id": proxy.get("uuid", ""),
                "aid": int(proxy.get("alterId", 0)),
                "net": proxy.get("network", "tcp"),
                "type": "none",
                "host": proxy.get("ws-opts", {}).get("headers", {}).get("Host", "") if isinstance(proxy.get("ws-opts"), dict) else "",
                "path": proxy.get("ws-opts", {}).get("path", "") if isinstance(proxy.get("ws-opts"), dict) else "",
                "tls": "tls" if proxy.get("tls") else "",
            }
            b64 = base64.urlsafe_b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode().rstrip("=")
            return f"vmess://{b64}"

        elif ptype == "trojan":
            pw = proxy.get("password", "")
            host = proxy.get("sni", server)
            params = f"?sni={host}&allowInsecure=1" if host else "?allowInsecure=1"
            frag = urllib.parse.quote(name, safe="")
            return f"trojan://{urllib.parse.quote(pw, safe='')}@{server}:{port}{params}#{frag}"

        elif ptype == "ss":
            method = proxy.get("cipher", "aes-256-gcm")
            pw = proxy.get("password", "")
            b64 = base64.urlsafe_b64encode(f"{method}:{pw}".encode()).decode().rstrip("=")
            frag = urllib.parse.quote(name, safe="")
            return f"ss://{b64}@{server}:{port}#{frag}"

        elif ptype == "http" or ptype == "https":
            return ""

        elif ptype == "hysteria2" or ptype == "hy2":
            pw = proxy.get("password", "")
            frag = urllib.parse.quote(name, safe="")
            return f"hysteria2://{urllib.parse.quote(pw, safe='')}@{server}:{port}#{frag}"

        elif ptype == "vless":
            uuid = proxy.get("uuid", "")
            net = proxy.get("network", "tcp")
            frag = urllib.parse.quote(name, safe="")
            return f"vless://{uuid}@{server}:{port}?type={net}&security=tls&sni={server}#{frag}"

        elif ptype == "anytls":
            pw = proxy.get("password", "")
            host = proxy.get("sni", server) or proxy.get("servername", server)
            frag = urllib.parse.quote(name, safe="")
            return f"anytls://{urllib.parse.quote(pw, safe='')}@{server}:{port}?sni={host}&allowInsecure=0#{frag}"

        return ""
    except:
        return ""


def quick_test(proxy):
    """Simple TCP connect test"""
    import socket
    server = proxy.get("server", "")
    port = proxy.get("port", 443)
    if not server:
        return False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((server, int(port)))
        s.close()
        return True
    except:
        return False


def main():
    parser = argparse.ArgumentParser(description="Aggregator")
    parser.add_argument("-s", "--server", default="", help="config file path")
    parser.add_argument("-r", "--retry", type=int, default=3, help="retry count")
    parser.add_argument("-t", "--timeout", type=int, default=5000, help="timeout ms")
    parser.add_argument("-u", "--url", default="", help="test url")
    args = parser.parse_args()

    server = args.server or os.environ.get("SUBSCRIBE_CONF", "")
    if not server:
        logger.error("config file not found")
        sys.exit(1)

    config = json.load(open(server, "r", encoding="utf8"))
    storage_conf = push.PushConfig.from_dict(config.get("storage", {}))
    if not storage_conf:
        logger.error("invalid storage config")
        sys.exit(1)

    pushtool = push.get_instance(storage_conf)
    storage_items = config.get("storage", {}).get("items", {})
    groups = config.get("groups", {})
    _, subconverter_bin = executable.which_bin()

    # Crawl
    crawled_subs = []
    crawl_config = config.get("crawl", {})
    if crawl_config.get("enable", True):
        crawled_subs = crawl.batch_crawl(crawl_config, config.get("domains", []), storage_conf)

    # Process all tasks
    all_proxies = []
    domains = config.get("domains", [])

    for item in domains:
        for sub in (item.get("sub", []) if isinstance(item.get("sub", []), list) else [item.get("sub", "")]):
            t = workflow.TaskConfig(name=item.get("name",""), bin_name=subconverter_bin, sub=sub,
                                    retry=args.retry, rate=item.get("rate", 5.0),
                                    rename=item.get("rename",""), exclude=item.get("exclude",""),
                                    liveness=item.get("liveness",True), ignorede=item.get("ignorede",True))
            all_proxies.extend(workflow.execute(t))

    for i, sub_url in enumerate(crawled_subs):
        t = workflow.TaskConfig(name=f"crawled-{i}", bin_name=subconverter_bin, sub=sub_url, retry=args.retry)
        all_proxies.extend(workflow.execute(t))

    logger.info(f"total proxies collected: {len(all_proxies)}")

    # TCP connect test
    alive = []
    for p in all_proxies:
        if quick_test(p):
            alive.append(p)

    logger.info(f"tcp check: {len(alive)} alive, {len(all_proxies) - len(alive)} dead")

    # Push outputs in correct format per target
    for group_name, group_conf in groups.items():
        for target, item_key in group_conf.get("targets", {}).items():
            if item_key not in storage_items:
                continue
            push_conf = storage_items[item_key]

            if target == "clash":
                output = yaml.dump({"proxies": alive}, allow_unicode=True, default_flow_style=False)

            elif target == "v2ray":
                # Build proper V2Ray subscription: base64(one link per line)
                links = []
                for p in alive:
                    link = proxy_to_v2ray_link(p)
                    if link:
                        links.append(link)
                raw = "\n".join(links)
                output = base64.b64encode(raw.encode()).decode()

            else:
                output = json.dumps(alive, indent=2)

            pushtool.push_to(content=output, config=push_conf, group=f"{group_name}::{target}")
            logger.info(f"group [{group_name}] done, count: {len(alive)}, target: {target}")


if __name__ == "__main__":
    main()
