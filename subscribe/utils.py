# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2022-07-15

import gzip
import json
import multiprocessing
import os
import platform
import random
import re
import socket
import ssl
import string
import subprocess
import sys
import time
import traceback
import typing
import urllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent import futures
from http.client import HTTPMessage, HTTPResponse

from logger import logger
from tqdm import tqdm
from urlvalidator import isurl

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FILEPATH_PROTOCAL = "file:///"
CHATGPT_FLAG = "-GPT"

DEFAULT_HTTP_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.9"}


def random_chars(length: int, punctuation: bool = False) -> str:
    length = max(length, 1)
    chars = string.ascii_letters + string.digits
    if punctuation:
        chars += string.punctuation
    return "".join(random.sample(chars, min(length, len(chars))))


def http_get(url, headers=None, params=None, retry=3, proxy="", interval=0, timeout=10, trace=False, max_size=None):
    if not isurl(url=url):
        return ""
    if retry <= 0:
        return ""
    headers = DEFAULT_HTTP_HEADERS if not headers else headers
    timeout = max(1, timeout)
    try:
        url = encoding_url(url=url)
        if params and isinstance(params, dict):
            data = urllib.parse.urlencode(params)
            url += ("&" if "?" in url else "?") + data
        request = urllib.request.Request(url=url, headers=headers)
        if proxy and (proxy.startswith("https://") or proxy.startswith("http://")):
            host = proxy[8:] if proxy.startswith("https://") else proxy[7:]
            request.set_proxy(host=host, type=proxy.split(":")[0])
        response = urllib.request.urlopen(request, timeout=timeout, context=CTX)
        content = response.read(max_size)
        try:
            content = str(content, encoding="utf8")
        except:
            content = gzip.decompress(content).decode("utf8")
        return content if response.getcode() == 200 else ""
    except Exception as e:
        if retry > 1:
            time.sleep(interval)
            return http_get(url, headers, params, retry - 1, proxy, interval, timeout, trace, max_size)
        return ""


def extract_domain(url, include_protocal=False):
    if not url:
        return ""
    start = url.find("//")
    if start == -1:
        start = -2
    end = url.find("/", start + 2)
    if end == -1:
        end = len(url)
    return url[start + 2 : end] if not include_protocal else url[:end]


def cmd(command, output=False):
    if not command:
        return False, ""
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) if output else subprocess.Popen(command)
    p.wait()
    content = ""
    if output:
        try:
            content = p.stdout.read().decode("utf8")
        except:
            content = ""
    return p.returncode == 0, content


def chmod(binfile):
    if not os.path.exists(binfile) or os.path.isdir(binfile):
        raise ValueError(f"cannot found bin file: {binfile}")
    s = str(platform.platform())
    if not s.startswith("Windows"):
        cmd(["chmod", "+x", binfile])


def encoding_url(url):
    if not url:
        return ""
    return url.strip()


def write_file(filename, lines):
    if not filename or not lines:
        return False
    if not isinstance(lines, str):
        lines = "\n".join(lines)
    filepath = os.path.abspath(os.path.dirname(filename))
    os.makedirs(filepath, exist_ok=True)
    with open(filename, "w+", encoding="UTF8") as f:
        f.write(lines)
        f.flush()
    return True


def isblank(text):
    return not text or type(text) != str or not text.strip()


def trim(text):
    return text.strip() if text and type(text) == str else ""


def load_dotenv(enviroment=".env"):
    path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    filename = os.path.join(path, enviroment or ".env")
    if not os.path.exists(filename):
        return
    with open(filename, mode="r", encoding="utf8") as f:
        for line in f.readlines():
            content = line.strip()
            if not content or content.startswith("#") or "=" not in content:
                continue
            words = content.split("=", maxsplit=1)
            k, v = words[0].strip(), words[1].strip()
            if k and v:
                os.environ[k] = v


def is_number(num):
    try:
        float(num)
        return True
    except ValueError:
        return False


def url_complete(url, secret=False):
    if isblank(url):
        return ""
    if not url.startswith("https://"):
        if url.startswith("http://") and secret:
            url = url.replace("http://", "https://")
        elif not url.startswith("http://"):
            url = f"https://{url}"
    return url


def load_emoji_pattern(filepath=""):
    filepath = trim(filepath)
    if not filepath:
        workspace = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        filepath = os.path.join(workspace, "subconverter", "snippets", "emoji.txt")
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        return {}
    patterns = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f.readlines():
            line = trim(line)
            if not line or line.startswith("#"):
                continue
            try:
                regex, emoji = line.rsplit(",", maxsplit=1)
                patterns[re.compile(regex, flags=re.I)] = emoji
            except ValueError:
                pass
    return patterns


def get_emoji(text, patterns, default=""):
    if not patterns or type(patterns) != dict or not text:
        return default
    for pattern, emoji in patterns.items():
        if pattern.search(text):
            return emoji
    return default


def multi_thread_run(func, tasks, num_threads=None, show_progress=False, description=""):
    if not func or not tasks or not isinstance(tasks, list):
        return []
    if num_threads is None or num_threads <= 0:
        num_threads = min(len(tasks), (os.cpu_count() or 1) * 2)
    funcname = getattr(func, "__name__", repr(func))
    results, starttime = [None] * len(tasks), time.time()
    with futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        if isinstance(tasks[0], (list, tuple)):
            collections = {executor.submit(func, *param): i for i, param in enumerate(tasks)}
        else:
            collections = {executor.submit(func, param): i for i, param in enumerate(tasks)}
        items = futures.as_completed(collections)
        if show_progress:
            items = tqdm(items, total=len(collections), desc=trim(description) or "Progress", leave=True)
        for future in items:
            try:
                index = collections[future]
                results[index] = future.result()
            except Exception as e:
                logger.error(f"function {funcname} execution generated an exception: {e}")
    logger.info(f"[Concurrent] multi-threaded execute [{funcname}] finished, count: {len(tasks)}, cost: {time.time()-starttime:.2f}s")
    return results
