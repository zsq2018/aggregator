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
        return ""
    except:
        return ""


def test_with_clash(proxies, timeout_ms):
    if not proxies:
        return []
    clash_workspace = os.path.join(PATH, "clash")
    clash_config = os.path.join(clash_workspace, "config.yaml")
    clash_bin = os.path.join(clash_workspace, "clash-linux-amd")
    if not os.path.exists(clash_bin):
        logger.error(f"clash not found, fallback TCP test")
        import socket as sk
        alive = []
        for p in proxies:
            try:
                s = sk.socket(sk.AF_INET, sk.SOCK_STREAM)
                s.settimeout(3)
                s.connect((p.get("server",""), int(p.get("port",443))))
                s.close()
                alive.append(p)
            except:
                pass
        return alive
    clash_conf = {"port": 7890, "log-level": "silent", "mode": "rule",
                  "proxies": proxies,
                  "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [p["name"] for p in proxies]}],
                  "rules": ["MATCH,PROXY"]}
    with open(clash_config, "w") as f:
        yaml.dump(clash_conf, f, allow_unicode=True)
    try:
        proc = subprocess.Popen([clash_bin, "-d", clash_workspace, "-f", clash_config],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(5)
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            logger.error(f"clash died: {err.decode()[:200]}")
            return []
        alive_names = set()
        for p in proxies:
            try:
                enc = urllib.parse.quote(p["name"], safe="")
                req = urllib.request.Request(f"http://127.0.0.1:9090/proxies/{enc}/delay?url={TEST_URL}&timeout={timeout_ms}")
                resp = urllib.request.urlopen(req, timeout=max(timeout_ms//1000+2,10))
                if resp.getcode() == 200:
                    d = json.loads(resp.read().decode()).get("delay", 0)
                    if 0 < d < 99999:
                        alive_names.add(p["name"])
            except:
                pass
        proc.terminate()
        alive = [p for p in proxies if p["name"] in alive_names]
        logger.info(f"clash test: {len(alive)} alive / {len(proxies)}")
        return alive
    except Exception as e:
        logger.error(f"clash error: {e}")
        try: proc.terminate()
        except: pass
        return []


def main():
    parser = argparse.ArgumentParser(description="Aggregator")
    parser.add_argument("-s", "--server", default="", help="config")
    parser.add_argument("-r", "--retry", type=int, default=3)
    parser.add_argument("-t", "--timeout", type=int, default=5000)
    args = parser.parse_args()

    server = args.server or os.environ.get("SUBSCRIBE_CONF", "")
    if not server:
        logger.error("no config"); sys.exit(1)

    config = json.load(open(server))
    sc = push.PushConfig.from_dict(config.get("storage", {}))
    if not sc:
        logger.error("bad storage"); sys.exit(1)
    pushtool = push.get_instance(sc)
    items = config.get("storage", {}).get("items", {})
    groups = config.get("groups", {})
    _, subconverter_bin = executable.which_bin()

    # Crawl
    crawled = []
    cc = config.get("crawl", {})
    if cc.get("enable", True):
        crawled = crawl.batch_crawl(cc, config.get("domains", []), sc)

    # Fetch
    all_px = []
    for item in config.get("domains", []):
        for sub in (item.get("sub", []) if isinstance(item.get("sub"), list) else [item.get("sub", "")]):
            t = workflow.TaskConfig(name=item.get("name",""), bin_name=subconverter_bin, sub=sub,
                                    retry=args.retry, rate=item.get("rate",5.0))
            all_px.extend(workflow.execute(t))
    for i, u in enumerate(crawled):
        t = workflow.TaskConfig(name=f"crawled-{i}", bin_name=subconverter_bin, sub=u, retry=args.retry)
        all_px.extend(workflow.execute(t))
    logger.info(f"collected: {len(all_px)}")

    alive = test_with_clash(all_px, args.timeout)

    # Push
    for gname, gconf in groups.items():
        for target, key in gconf.get("targets", {}).items():
            if key not in items:
                continue
            if target == "clash":
                out = yaml.dump({"proxies": alive}, allow_unicode=True)
            elif target == "v2ray":
                links = [proxy_to_v2ray_link(p) for p in alive if proxy_to_v2ray_link(p)]
                out = base64.b64encode("\n".join(links).encode()).decode()
            else:
                out = json.dumps(alive, indent=2)
            pushtool.push_to(content=out, config=items[key], group=f"{gname}::{target}")
            logger.info(f"done: {gname}/{target} = {len(alive)}")


if __name__ == "__main__":
    main()
