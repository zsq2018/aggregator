# -*- coding: utf-8 -*-

import json
import os
import re
from dataclasses import dataclass

import renewal
import utils
from airport import ANOTHER_API_PREFIX, AirPort
from logger import logger
from origin import Origin
from push import PushTo


@dataclass
class TaskConfig:
    name: str = ""
    bin_name: str = ""
    taskid: int = -1
    domain: str = ""
    sub: str = ""
    index: int = 1
    retry: int = 3
    rate: float = 20.0
    renew: dict = None
    coupon: str = ""
    rename: str = ""
    exclude: str = ""
    include: str = ""
    chatgpt: dict = None
    liveness: bool = True
    disable_insecure: bool = False
    ignorede: bool = False
    special_protocols: bool = False
    rigid: bool = True
    chuck: bool = False
    invite_code: str = ""
    api_prefix: str = "/api/v1/"


def execute(task_conf):
    if not task_conf or not isinstance(task_conf, TaskConfig):
        return []
    obj = AirPort(name=task_conf.name, site=task_conf.domain, sub=task_conf.sub,
                  rename=task_conf.rename, exclude=task_conf.exclude, include=task_conf.include,
                  liveness=task_conf.liveness, coupon=task_conf.coupon, api_prefix=task_conf.api_prefix)
    logger.info(f"start fetch proxy: name=[{task_conf.name}] domain=[{obj.ref}]")
    if task_conf.renew:
        sub_url = renewal.add_traffic_flow(domain=obj.ref, params=task_conf.renew, jsonify=(obj.api_prefix == ANOTHER_API_PREFIX))
        if sub_url and not obj.registed:
            obj.registed = True
            obj.sub = sub_url
    cookie, authorization = obj.get_subscribe(retry=task_conf.retry, rigid=task_conf.rigid,
                                              chuck=task_conf.chuck, invite_code=task_conf.invite_code)
    proxies = obj.parse(cookie=cookie, auth=authorization, retry=task_conf.retry, rate=task_conf.rate,
                        bin_name=task_conf.bin_name, disable_insecure=task_conf.disable_insecure,
                        ignore_exclude=task_conf.ignorede, chatgpt=task_conf.chatgpt,
                        special_protocols=task_conf.special_protocols)
    logger.info(f"finished fetch proxy: name=[{task_conf.name}] domain=[{obj.ref}] count=[{len(proxies)}]")
    return proxies


def liveness_fillter(proxies):
    """Split proxies into check-needed and no-check lists"""
    if not proxies:
        return [], []
    checks, nochecks = [], []
    for p in proxies:
        if not isinstance(p, dict):
            continue
        liveness = p.pop("liveness", True)
        if liveness:
            p.pop("sub", "")
            checks.append(p)
        else:
            p.pop("sub", "")
            nochecks.append(p)
    return checks, nochecks


def executewrapper(task_conf):
    if not task_conf:
        return (-1, [])
    return (task_conf.taskid, execute(task_conf=task_conf))


def cleanup(filepath, filenames):
    if not filepath or not filenames:
        return
    for name in filenames:
        filename = os.path.join(filepath, name)
        if os.path.exists(filename):
            os.remove(filename)


def dedup_task(tasks):
    if not tasks:
        return []
    items = []
    for task in tasks:
        if not exists(tasks=items, task=task):
            items.append(task)
    return items


def exists(tasks, task):
    if not isinstance(task, TaskConfig):
        return True
    if not tasks:
        return False
    for item in tasks:
        if task.sub:
            if task.sub == item.sub:
                return True
        else:
            if task.domain == item.domain and task.index == item.index:
                return True
    return False


def merge_config(configs):
    if not configs:
        return []
    items = []
    for conf in configs:
        if not isinstance(conf, dict):
            continue
        sub = conf.get("sub", "")
        if isinstance(sub, list) and len(sub) <= 1:
            sub = sub[0] if sub else ""
        if isinstance(sub, list) or conf.get("renew", {}):
            items.append(conf)
            continue
        found = False
        conf["sub"] = sub
        for item in items:
            if sub and sub == item.get("sub", ""):
                found = True
                break
        if not found:
            items.append(conf)
    return items


def refresh(config, push, alives, filepath="", skip_remark=False):
    if not config or not push:
        return
    update_conf = config.get("update", {})
    if not update_conf.get("enable", False):
        return
    if not push.validate(config=update_conf):
        return
    content = json.dumps(config)
    if filepath:
        directory = os.path.abspath(os.path.dirname(filepath))
        os.makedirs(directory, exist_ok=True)
        with open(filepath, "w+", encoding="UTF8") as f:
            f.write(content)
            f.flush()
    push.push_to(content=content, config=update_conf, group="update")
