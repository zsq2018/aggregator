def test_with_clash(proxies, timeout_ms):
    if not proxies:
        return []
    clash_workspace = os.path.join(PATH, "clash")
    clash_config = os.path.join(clash_workspace, "config.yaml")
    clash_bin = os.path.join(clash_workspace, "clash-linux-amd")
    if not os.path.exists(clash_bin):
        logger.error(f"clash not found at {clash_bin}, falling back to TCP test")
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
    clash_conf = {"port": 7890, "socks-port": 7891, "log-level": "silent",
                  "allow-lan": False, "mode": "rule",
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
            logger.error(f"clash exited early: {err.decode()[:300]}")
            return []
        api_url = "http://127.0.0.1:9090"
        alive_names = set()
        for p in proxies:
            name = p.get("name", "")
            if not name:
                continue
            try:
                encoded = urllib.parse.quote(name, safe="")
                req = urllib.request.Request(f"{api_url}/proxies/{encoded}/delay?url={TEST_URL}&timeout={timeout_ms}")
                resp = urllib.request.urlopen(req, timeout=max(timeout_ms//1000+2,10))
                if resp.getcode() == 200:
                    data = json.loads(resp.read().decode())
                    d = data.get("delay", 0)
                    if 0 < d < 99999:
                        alive_names.add(name)
            except:
                pass
        proc.terminate()
        alive = [p for p in proxies if p.get("name","") in alive_names]
        logger.info(f"clash test: {len(alive)} alive, {len(proxies)-len(alive)} dead")
        return alive
    except Exception as e:
        logger.error(f"clash test error: {e}")
        try: proc.terminate()
        except: pass
        return []
