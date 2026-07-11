# -*- coding: utf-8 -*-

import base64
import copy
import itertools
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback
from copy import deepcopy
from dataclasses import dataclass, field

import crawl
import executable
import location
import push
import utils
import workflow
import yaml
from airport import AirPort, ANOTHER_API_PREFIX
from logger import logger
from origin import Origin

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def load_configs(server, push_config):
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
    parser.add_argument("-c", "--check", action="store_true", help="only check proxies are alive")
    parser.add_argument("-f", "--flexible", action="store_true", help="flexible register mode")
    parser.add_argument("-o", "--overwrite", action="store_true", help="overwrite remainder proxies")
    parser.add_argument("-i", "--invisible", action="store_true", help="hide progress bar")
    parser.add_argument("-e", "--environment", default="", help="environment file")
    parser.add_argument("-u", "--url", default="", help="test url")
    args = parser.parse_args()

    server = args.server or os.environ.get("SUBSCRIBE_CONF", "")
    if not server:
        logger.error("config file not found")
        sys.exit(1)
    
    # Load config
    config = load_configs(server, None)
    
    # Get storage config
    storage_conf = push.PushConfig.from_dict(config.get("storage", {}))
    if not storage_conf:
        logger.error("storage config is invalid")
        sys.exit(1)
    
    # Get push instance
    pushtool = push.get_instance(storage_conf)
    
    # Process crawl config
    crawl_config = config.get("crawl", {})
    if crawl_config.get("enable", True):
        crawl.batch_crawl(crawl_config, config.get("domains", []), storage_conf)
    
    # Process domains
    domains = config.get("domains", [])
    if not domains:
        logger.error("no domains configured")
        return
    
    groups = config.get("groups", {})
    storage_items = storage_conf.get("items", {}) if hasattr(storage_conf, 'items') else config.get("storage", {}).get("items", {})
    
    # Get binaries
    clash_bin, subconverter_bin = executable.which_bin()
    
    # Build task configs
    tasks = []
    for item in domains:
        name = item.get("name", "")
        domain = item.get("domain", "")
        sub_list = item.get("sub", [])
        if isinstance(sub_list, str):
            sub_list = [sub_list]
        
        for i, sub in enumerate(sub_list):
            task = workflow.TaskConfig(
                name=name,
                bin_name=subconverter_bin,
                taskid=i,
                domain=domain,
                sub=sub,
                index=i + 1,
                retry=args.retry,
                rate=item.get("rate", 2.5),
                rename=item.get("rename", ""),
                exclude=item.get("exclude", ""),
                include=item.get("include", ""),
                liveness=item.get("liveness", True),
                ignorede=item.get("ignorede", True),
                coupon=item.get("coupon", ""),
                renew=item.get("renew", {}),
                chatgpt=item.get("chatgpt", {}),
                disable_insecure=item.get("secure", False),
                special_protocols=item.get("special", False),
                rigid=not args.flexible,
            )
            tasks.append(task)
    
    # Execute tasks
    all_proxies = []
    for task in tasks:
        proxies = workflow.execute(task)
        all_proxies.extend(proxies)
    
    # Filter and test
    check_list, no_check_list = workflow.liveness_fillter(all_proxies)
    
    # Start clash for testing
    import yaml
    clash_workspace = os.path.join(PATH, "clash")
    clash_config = os.path.join(clash_workspace, "config.yaml")
    
    # Generate clash config
    clash_conf = {"port": 7890, "socks-port": 7891, "log-level": "silent", "mode": "rule", "proxies": [], "proxy-groups": [], "rules": []}
    
    if check_list:
        clash_conf["proxies"] = check_list
        clash_conf["proxy-groups"] = [
            {"name": "proxy", "type": "select", "proxies": [p["name"] for p in check_list]},
            {"name": "auto", "type": "url-test", "proxies": [p["name"] for p in check_list], "url": "https://www.gstatic.com/generate_204", "interval": 300}
        ]
        clash_conf["rules"] = ["MATCH,proxy"]
        
        utils.write_file(clash_config, yaml.dump(clash_conf, allow_unicode=True))
        
        # Start clash
        clash_path = os.path.join(clash_workspace, clash_bin)
        utils.chmod(clash_path)
        proc = subprocess.Popen([clash_path, "-d", clash_workspace, "-f", clash_config],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        
        # Test proxies
        api_url = "http://127.0.0.1:9090"
        test_url = args.url or "https://www.gstatic.com/generate_204"
        alives = location.check_proxies(check_list, api_url, args.timeout // 1000, test_url, 0)
        
        proc.terminate()
        
        alive_list = [p for p in check_list if p.get("name", "") in alives]
        logger.info(f"proxies check finished, total: {len(check_list)}, alive: {len(alive_list)}, dead: {len(check_list) - len(alive_list)}")
        
        all_alive = alive_list + no_check_list
    else:
        all_alive = no_check_list
        logger.info(f"no proxies need to check, total: {len(all_alive)}")
    
    # Convert and push
    for group_name, group_conf in groups.items():
        targets = group_conf.get("targets", {})
        for target, item_key in targets.items():
            if item_key not in storage_items:
                logger.error(f"missing storage configuration for group {group_name} to convert type to {target}")
                continue
            
            # Get the raw subscription URL
            push_conf = storage_items[item_key]
            
            # Build clash config for output
            output_conf = {"proxies": all_alive}
            if not group_conf.get("list", True):
                output_conf["proxy-groups"] = [
                    {"name": "Proxy", "type": "select", "proxies": [p["name"] for p in all_alive]}
                ]
                output_conf["rules"] = ["MATCH,Proxy"]
            
            output_content = yaml.dump(output_conf, allow_unicode=True) if target == "clash" else json.dumps(all_proxies, ensure_ascii=False)
            
            if target == "clash":
                # Push as yaml
                pushtool.push_to(content=output_content, config=push_conf, group=f"{group_name}::{target}")
            elif target == "v2ray":
                # Build v2ray links
                links = []
                for p in all_alive:
                    if p.get("type") == "vmess":
                        v = base64.b64encode(json.dumps({"v": "2", "ps": p.get("name", ""), "add": p.get("server", ""), "port": p.get("port", 443), "id": p.get("uuid", ""), "aid": p.get("alterId", 0), "net": p.get("network", "tcp"), "type": "none", "host": "", "path": "", "tls": ""}).encode()).decode()
                        links.append(f"vmess://{v}")
                output_content = "\n".join(links)
                pushtool.push_to(content=output_content, config=push_conf, group=f"{group_name}::{target}")
            else:
                pushtool.push_to(content=json.dumps(all_alive, ensure_ascii=False), config=push_conf, group=f"{group_name}::{target}")
            
            logger.info(f"group [{group_name}] process finished, count: {len(all_alive)}, target: {target}")


if __name__ == "__main__":
    main()
