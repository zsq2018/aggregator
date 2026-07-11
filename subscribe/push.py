# -*- coding: utf-8 -*-

# @Author  : wzdnzd
# @Time    : 2022-07-15

import json
import os
import traceback
import urllib
import urllib.request
from dataclasses import dataclass
from http.client import HTTPResponse

import utils
from logger import logger
from urlvalidator import isurl

LOCAL_STORAGE = "local"


class PushTo(object):
    def __init__(self, token: str = "", base: str = "", domain: str = "") -> None:
        self.name = ""
        self.method = "PUT"
        self.token = token

    def push_file(self, filepath: str, config: dict, group: str = "", retry: int = 5) -> bool:
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            logger.error(f"[PushFileError] file {filepath} not found")
            return False

        content = " "
        with open(filepath, "r", encoding="utf8") as f:
            content = f.read()

        return self.push_to(content=content, config=config, group=group, retry=retry)

    def push_to(self, content: str, config: dict, group: str = "", retry: int = 5, **kwargs) -> bool:
        if not self.validate(config=config):
            logger.error(f"[PushError] push config is invalidate, domain: {self.name}")
            return False

        url, data, headers = self._generate_payload(content=content, config=config)

        try:
            request = urllib.request.Request(url=url, data=data, headers=headers, method=self.method)
            response = urllib.request.urlopen(request, timeout=60, context=utils.CTX)
            if self._is_success(response):
                logger.info(f"[PushSuccess] push subscribes information to {self.name} successed, group=[{group}]")
                return True
            return False
        except Exception as e:
            retry -= 1
            if retry > 0:
                return self.push_to(content, config, group, retry)
            return False

    def _is_success(self, response: HTTPResponse) -> bool:
        return response and response.getcode() == 200

    def _generate_payload(self, content: str, config: dict) -> tuple:
        raise NotImplementedError

    def validate(self, config: dict) -> bool:
        raise NotImplementedError

    def filter_push(self, config: dict) -> dict:
        raise NotImplementedError

    def raw_url(self, config: dict) -> str:
        raise NotImplementedError


class PushToGist(PushTo):
    def __init__(self, token: str) -> None:
        super().__init__(token=token)
        self.name = "gist"
        self.api_address = "https://api.github.com/gists"
        self.domain = "https://gist.githubusercontent.com"
        self.method = "PATCH"

    def validate(self, config: dict) -> bool:
        if not isinstance(config, dict):
            return False
        gistid = config.get("gistid", "")
        filename = config.get("filename", "")
        return bool(self.token.strip() and gistid.strip() and filename.strip())

    def _generate_payload(self, content: str, config: dict) -> tuple:
        gistid = config.get("gistid", "")
        filename = config.get("filename", "")
        url = f"{self.api_address}/{gistid}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        data = json.dumps({"files": {filename: {"content": content}}}).encode("UTF8")
        return url, data, headers

    def filter_push(self, config: dict) -> dict:
        if not self.token or not isinstance(config, dict):
            return {}
        return {k: v for k, v in config.items() if v.get("gistid", "") and v.get("filename", "")}

    def raw_url(self, config: dict) -> str:
        username = config.get("username", "")
        gistid = config.get("gistid", "")
        filename = config.get("filename", "")
        if not username or not gistid or not filename:
            return ""
        return f"{self.domain}/{username}/{gistid}/raw/{filename}"


class PushToLocal(PushTo):
    def __init__(self) -> None:
        super().__init__(token="")
        self.name = "local"

    def validate(self, config: dict) -> bool:
        return config is not None and bool(config.get("fileid", ""))

    def push_to(self, content: str, config: dict, group: str = "", retry: int = 5) -> bool:
        folder = config.get("folderid", "")
        filename = config.get("fileid", "")
        basedir = os.path.abspath(os.environ.get("LOCAL_BASEDIR", ""))
        try:
            savepath = os.path.abspath(os.path.join(basedir, folder, filename))
            os.makedirs(os.path.dirname(savepath), exist_ok=True)
            with open(savepath, "w+", encoding="utf8") as f:
                f.write(content)
                f.flush()
            logger.info(f"[PushInfo] push subscribes information to {self.name} successed, group=[{group}]")
            return True
        except Exception as e:
            logger.error(f"[PushError] {e}")
            return False

    def filter_push(self, config: dict) -> dict:
        return {k: v for k, v in config.items() if v.get("fileid", "")}

    def raw_url(self, config: dict) -> str:
        folderid = config.get("folderid", "")
        fileid = config.get("fileid", "")
        return f"file://{os.path.abspath(os.path.join(folderid, fileid))}"


SUPPORTED_ENGINES = set(["gist", "local"])


@dataclass
class PushConfig(object):
    engine: str = ""
    token: str = ""
    base: str = ""
    domain: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PushConfig":
        if not data or type(data) != dict:
            return None
        engine = data.get("engine", "")
        if engine not in SUPPORTED_ENGINES:
            return None
        return cls(engine=engine, token=data.get("token", ""), base=data.get("base", ""), domain=data.get("domain", ""))


def get_instance(config: PushConfig) -> PushTo:
    if not config or not isinstance(config, PushConfig):
        raise ValueError("[PushError] invalid push config")
    engine = config.engine
    token = config.token or os.environ.get("PUSH_TOKEN", "")
    if engine != "local" and not token:
        raise ValueError(f"[PushError] not found 'PUSH_TOKEN' in environment variables")
    if engine == "gist":
        return PushToGist(token=token)
    return PushToLocal()
