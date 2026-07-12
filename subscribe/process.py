# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import crawl
import executable
import push
import utils
import workflow
import yaml
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
TEST_URL = "https://www.gstatic.com/generate_204"


def proxy_to_v2ray_link(proxy):
    ptype = proxy.get("type", "")
    name = proxy.get("name", "unknown")
    server = proxy.get("server", "")
    port = proxy.get("port", 443)
    try:
        if ptype == "vmess":
            cfg = {"v": "2", "ps": name, "add": server, "port": int(port),
                   "id": proxy.get("uuid", ""), "aid": int(proxy.get("alterId", 0)),
                   "net": proxy.get("network", "tcp"), "type": "none",
                   "host": "", "path": "", "tls": "tls" if proxy.get("tls") else ""}
            if isinstance(proxy.get("ws-opts"), dict):
                cfg["host"] = proxy["ws-opts"].get("headers", {}).get("Host", "")
                cfg["path"] = proxy["ws-opts"].get("path", "")
            b64 = base64.urlsafe_b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode().rstrip("=")
            return f"vmess://{b64}"
        elif ptype == "trojan":
            pw = proxy.get("password", "")
            host = proxy.get("sni", server)
            return f"trojan://{urllib.parse.quote(pw, safe='')}@{server}:{port}?sni={host}&allowInsecure=1#{urllib.parse.quote(name, safe='')}"
        elif ptype == "ss":
            method = proxy.get("cipher", "aes-256-gcm")
            pw = proxy.get("password", "")
            b64 = base64.urlsafe_b64encode(f"{method}:{pw}".encode()).decode().rstrip("=")
            return f"ss://{b64}@{server}:{port}#{urllib.parse.quote(name, safe='')}"
        elif ptype == "anytls":
            pw = proxy.get("password", "")
            host = proxy.get("sni", server) or proxy.get("servername", server)
            return f"anytls://{urllib.parse.quote(pw, safe='')}@{server}:{port}?sni={host}#{urllib.parse.quote(name, safe='')}"
        elif ptype == "hysteria2" or ptype == "hy2":
            pw = proxy.get("password", "")
            return f"hysteria2://{urllib.parse.quote(pw, safe='')}@{server}:{port}#{urllib.parse.quote(name, safe='')}"
        elif ptype == "vless":
            uuid = proxy.get("uuid", "")
            net = proxy.get("network", "tcp")
            return f"vless://{uuid}@{server}:{port}?type={net}&security=tls#{urllib.parse.quote(name, safe='')}"
        return ""
    except:
        return ""


def test_with_clash(proxies, timeout_ms):
    """Use clash to test proxies, returns only working ones"""
    if not proxies:
        return []

    clash_workspace = os.path.join(PATH, "clash")
    clash_config = os.path.join(clash_workspace, "config.yaml")
    clash_bin = os.path.join(clash_workspace, "clash-linux-amd")

    if not os.path.exists(clash_bin):
        logger.error("clash binary not found, falling back to TCP test")
        import socket
        alive = []
        for p in proxies:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5)
                s.connect((p.get("server",""), int(p.get("port",443))))
                s.close()
                alive.append(p)
            except:
                pass
        return alive

    # Build clash config
    clash_conf = {
        "port": 7890, "socks-port": 7891, "log-level": "silent",
        "allow-lan": False, "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [{
            "name": "PROXY", "type": "select",
            "proxies": [p["name"] for p in proxies]
        }],
        "rules": ["MATCH,PROXY"]
    }

    with open(clash_config, "w", encoding="utf8") as f:
        yaml.dump(clash_conf, f, allow_unicode=True, default_flow_style=False)

    try:
        proc = subprocess.Popen([clash_bin, "-d", clash_workspace, "-f", clash_config],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)

        api_url = "http://127.0.0.1:9090"
        alive_names = set()

        for p in proxies:
            name = p.get("name", "")
            if not name:
                continue
            try:
                encoded = urllib.parse.quote(name, safe="")
                url = f"{api_url}/proxies/{encoded}/delay?url={TEST_URL}&timeout={timeout_ms}"
                req = urllib.request.Request(url)
                resp = urllib.request.urlopen(req, timeout=max(timeout_ms // 1000 + 2, 10))
                if resp.getcode() == 200:
                    data = json.loads(resp.read().decode())
                    delay = data.get("delay", 0)
                    if 0 < delay < 99999:
                        alive_names.add(name)
            except:
                pass

        proc.terminate()
        alive = [p for p in proxies if p.get("name", "") in alive_names]
        logger.info(f"clash test: {len(alive)} alive, {len(proxies) - len(alive)} dead")
        return alive

    except Exception as e:
        logger.error(f"clash test error: {e}")
        try:
            proc.terminate()
        except:
            pass
        return []


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

    # Use clash for real protocol-level testing
    alive = test_with_clash(all_proxies, args.timeout)

    # Push outputs
    for group_name, group_conf in groups.items():
        for target, item_key in group_conf.get("targets", {}).items():
            if item_key not in storage_items:
                continue
            push_conf = storage_items[item_key]

            if target == "clash":
                output = yaml.dump({"proxies": alive}, allow_unicode=True, default_flow_style=False)
            elif target == "v2ray":
                links = [proxy_to_v2ray_link(p) for p in alive]
                links = [l for l in links if l]
                output = base64.b64encode("\n".join(links).encode()).decode()
            else:
                output = json.dumps(alive, indent=2)

            pushtool.push_to(content=output, config=push_conf, group=f"{group_name}::{target}")
            logger.info(f"group [{group_name}] done, count: {len(alive)}, target: {target}")


if __name__ == "__main__":
    main()
