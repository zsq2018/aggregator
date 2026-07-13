# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os
import socket
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
            cfg = {"v":"2","ps":name,"add":server,"port":int(port),
                   "id":proxy.get("uuid",""),"aid":int(proxy.get("alterId",0)),
                   "net":proxy.get("network","tcp"),"type":"none","host":"","path":"",
                   "tls":"tls" if proxy.get("tls") else ""}
            if isinstance(proxy.get("ws-opts"), dict):
                cfg["host"] = proxy["ws-opts"].get("headers",{}).get("Host","")
                cfg["path"] = proxy["ws-opts"].get("path","")
            b64 = base64.urlsafe_b64encode(json.dumps(cfg,separators=(",",":")).encode()).decode().rstrip("=")
            return f"vmess://{b64}"
        elif ptype == "trojan":
            pw = proxy.get("password","")
            host = proxy.get("sni",server)
            return f"trojan://{urllib.parse.quote(pw,safe='')}@{server}:{port}?sni={host}&allowInsecure=1#{urllib.parse.quote(name,safe='')}"
        elif ptype == "ss":
            m = proxy.get("cipher","aes-256-gcm")
            pw = proxy.get("password","")
            b64 = base64.urlsafe_b64encode(f"{m}:{pw}".encode()).decode().rstrip("=")
            return f"ss://{b64}@{server}:{port}#{urllib.parse.quote(name,safe='')}"
        elif ptype == "anytls":
            pw = proxy.get("password","")
            host = proxy.get("sni",server) or proxy.get("servername",server)
            return f"anytls://{urllib.parse.quote(pw,safe='')}@{server}:{port}?sni={host}#{urllib.parse.quote(name,safe='')}"
        return ""
    except:
        return ""


def test_tcp(proxies, timeout_s):
    alive = []
    for p in proxies:
        try:
            s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            s.settimeout(timeout_s)
            s.connect((p["server"],int(p["port"])))
            s.close()
            alive.append(p)
        except:
            pass
    return alive


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-s","--server",default="")
    p.add_argument("-r","--retry",type=int,default=3)
    p.add_argument("-t","--timeout",type=int,default=5000)
    args = p.parse_args()
    server = args.server or os.environ.get("SUBSCRIBE_CONF","")
    if not server: logger.error("no config"); sys.exit(1)
    cfg = json.load(open(server))
    sc = push.PushConfig.from_dict(cfg.get("storage",{}))
    if not sc: logger.error("bad storage"); sys.exit(1)
    pt = push.get_instance(sc)
    items = cfg.get("storage",{}).get("items",{})
    groups = cfg.get("groups",{})
    _,subc = executable.which_bin()

    crawled = []
    cc = cfg.get("crawl",{})
    if cc.get("enable",True):
        crawled = crawl.batch_crawl(cc, cfg.get("domains",[]), sc)

    px = []
    for item in cfg.get("domains",[]):
        for sub in (item.get("sub",[]) if isinstance(item.get("sub"),list) else [item.get("sub","")]):
            t = workflow.TaskConfig(name=item.get("name",""),bin_name=subc,sub=sub,retry=args.retry,rate=item.get("rate",5.0))
            try: px.extend(workflow.execute(t))
            except: pass
    for i, u in enumerate(crawled):
        t = workflow.TaskConfig(name=f"crawl-{i}",bin_name=subc,sub=u,retry=args.retry)
        try: px.extend(workflow.execute(t))
        except: pass
    logger.info(f"collected: {len(px)}")

    alive = []
    cb = os.path.join(PATH,"clash","clash-linux-amd")
    if os.path.exists(cb) and len(px) > 0:
        cw = os.path.join(PATH,"clash")
        cf = os.path.join(cw,"config.yaml")
        cc = {"port":7890,"log-level":"silent","mode":"rule",
              "proxies":px,
              "proxy-groups":[{"name":"PROXY","type":"select","proxies":[p["name"] for p in px]}],
              "rules":["MATCH,PROXY"]}
        with open(cf,"w") as f: yaml.dump(cc,f,allow_unicode=True)
        try:
            proc = subprocess.Popen([cb,"-d",cw,"-f",cf],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(8)
            if proc.poll() is None:
                for p in px:
                    try:
                        enc = urllib.parse.quote(p["name"],safe="")
                        to = max(args.timeout,3000)
                        req = urllib.request.Request(f"http://127.0.0.1:9090/proxies/{enc}/delay?url={TEST_URL}&timeout={to}")
                        resp = urllib.request.urlopen(req, timeout=max(to//1000+2,8))
                        if resp.getcode()==200:
                            d = json.loads(resp.read().decode()).get("delay",0)
                            if 0<d<99999: alive.append(p)
                    except: pass
                proc.terminate()
        except: pass

    # Clash returned 0 but we have proxies: fallback to TCP
    if len(alive) == 0 and len(px) > 0:
        logger.info("clash returned 0, fallback to TCP test")
        alive = test_tcp(px, 3)
    
    logger.info(f"tested: {len(alive)}/{len(px)} alive")

    for gname,gconf in groups.items():
        for target,key in gconf.get("targets",{}).items():
            if key not in items: continue
            if target=="clash":
                out=yaml.dump({"proxies":alive},allow_unicode=True,default_flow_style=False)
            elif target=="v2ray":
                links=[proxy_to_v2ray_link(p) for p in alive if proxy_to_v2ray_link(p)]
                out=base64.b64encode("\n".join(links).encode()).decode()
            else:
                out=json.dumps(alive,indent=2)
            pt.push_to(content=out,config=items[key],group=f"{gname}::{target}")
            logger.info(f"done: {gname}/{target} = {len(alive)}")

if __name__=="__main__":
    main()
