# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import sys
import urllib.request

import crawl
import executable
import push
import utils
import workflow
import yaml
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


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

    # Quick TCP connect test instead of clash
    alive = []
    for p in all_proxies:
        if quick_test(p):
            alive.append(p)

    logger.info(f"tcp check: {len(alive)} alive, {len(all_proxies) - len(alive)} dead")

    # Push output
    for group_name, group_conf in groups.items():
        for target, item_key in group_conf.get("targets", {}).items():
            if item_key not in storage_items:
                continue
            push_conf = storage_items[item_key]
            output = yaml.dump({"proxies": alive}, allow_unicode=True) if target == "clash" else json.dumps(alive, indent=2)
            pushtool.push_to(content=output, config=push_conf, group=f"{group_name}::{target}")
            logger.info(f"group [{group_name}] done, count: {len(alive)}, target: {target}")


if __name__ == "__main__":
    main()
