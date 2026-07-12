# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import subprocess
import sys
import time

import crawl
import executable
import location
import push
import utils
import workflow
import yaml
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def load_configs(server):
    with open(server, "r", encoding="utf8") as f:
        config = json.loads(f.read())
    if not config:
        raise ValueError("config is empty")
    return config


def main():
    parser = argparse.ArgumentParser(description="Aggregator - Proxy Aggregation Platform")
    parser.add_argument("-s", "--server", default="", help="config file path")
    parser.add_argument("-n", "--num", type=int, default=64, help="thread num")
    parser.add_argument("-r", "--retry", type=int, default=3, help="retry count")
    parser.add_argument("-t", "--timeout", type=int, default=5000, help="timeout milliseconds")
    parser.add_argument("-c", "--check", action="store_true", help="only check proxies")
    parser.add_argument("-f", "--flexible", action="store_true", help="flexible register mode")
    parser.add_argument("-i", "--invisible", action="store_true", help="hide progress bar")
    parser.add_argument("-u", "--url", default="", help="test url")
    args = parser.parse_args()

    server = args.server or os.environ.get("SUBSCRIBE_CONF", "")
    if not server:
        logger.error("config file not found")
        sys.exit(1)

    config = load_configs(server)
    storage_conf = push.PushConfig.from_dict(config.get("storage", {}))
    if not storage_conf:
        logger.error("storage config is invalid")
        sys.exit(1)

    pushtool = push.get_instance(storage_conf)
    storage_items = config.get("storage", {}).get("items", {})

    # Crawl
    crawled_subs = []
    crawl_config = config.get("crawl", {})
    if crawl_config.get("enable", True):
        crawled_subs = crawl.batch_crawl(crawl_config, config.get("domains", []), storage_conf)

    # Build task list from both domains and crawled subs
    domains = config.get("domains", [])
    groups = config.get("groups", {})
    _, subconverter_bin = executable.which_bin()

    all_proxies = []

    # Process configured domains
    for item in domains:
        name = item.get("name", "")
        sub_list = item.get("sub", [])
        if isinstance(sub_list, str):
            sub_list = [sub_list]
        for sub in sub_list:
            task = workflow.TaskConfig(
                name=name, bin_name=subconverter_bin, domain=item.get("domain", ""),
                sub=sub, retry=args.retry, rate=item.get("rate", 2.5),
                rename=item.get("rename", ""), exclude=item.get("exclude", ""),
                include=item.get("include", ""), liveness=item.get("liveness", True),
                ignorede=item.get("ignorede", True), coupon=item.get("coupon", ""),
                renew=item.get("renew", {}), rigid=not args.flexible,
            )
            proxies = workflow.execute(task)
            all_proxies.extend(proxies)

    # Process crawled subscriptions
    for i, sub_url in enumerate(crawled_subs):
        task = workflow.TaskConfig(
            name=f"crawled-{i}", bin_name=subconverter_bin,
            sub=sub_url, retry=args.retry,
            liveness=True, ignorede=True,
        )
        proxies = workflow.execute(task)
        all_proxies.extend(proxies)

    logger.info(f"total proxies collected: {len(all_proxies)}")

    # Filter and test
    check_list, no_check_list = workflow.liveness_fillter(all_proxies)

    if check_list:
        clash_workspace = os.path.join(PATH, "clash")
        clash_config = os.path.join(clash_workspace, "config.yaml")
        clash_conf = {"port": 7890, "log-level": "silent", "mode": "rule",
                      "proxies": check_list,
                      "proxy-groups": [{"name": "proxy", "type": "select",
                                        "proxies": [p["name"] for p in check_list]}],
                      "rules": ["MATCH,proxy"]}
        utils.write_file(clash_config, yaml.dump(clash_conf, allow_unicode=True))

        clash_path = os.path.join(clash_workspace, "clash-linux-amd")
        utils.chmod(clash_path)
        proc = subprocess.Popen([clash_path, "-d", clash_workspace, "-f", clash_config],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)

        api_url = "http://127.0.0.1:9090"
        test_url = args.url or "https://www.gstatic.com/generate_204"
        alives = location.check_proxies(check_list, api_url, max(args.timeout // 1000, 5), test_url, 0)
        proc.terminate()

        alive_list = [p for p in check_list if p.get("name", "") in alives]
        logger.info(f"proxies check finished, total: {len(check_list)}, alive: {len(alive_list)}, dead: {len(check_list)-len(alive_list)}")
        all_alive = alive_list + no_check_list
    else:
        all_alive = no_check_list

    # Push to Gist
    for group_name, group_conf in groups.items():
        targets = group_conf.get("targets", {})
        for target, item_key in targets.items():
            if item_key not in storage_items:
                logger.error(f"missing storage for {group_name} -> {target}")
                continue
            push_conf = storage_items[item_key]
            output_content = yaml.dump({"proxies": all_alive}, allow_unicode=True) if target == "clash" else json.dumps(all_alive, ensure_ascii=False, indent=2)
            pushtool.push_to(content=output_content, config=push_conf, group=f"{group_name}::{target}")
            logger.info(f"group [{group_name}] done, count: {len(all_alive)}, target: {target}")


if __name__ == "__main__":
    main()
