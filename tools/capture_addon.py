"""mitmproxy addon: record every HTTP(S) request/response and websocket message Blaston makes.

Writes to capture/<session>/:
  flows.jsonl          one JSON object per HTTP exchange / websocket message (chronological)
  by_host/<host>.jsonl the same, split per host
  endpoints.txt        running summary: count  METHOD host/path  (status codes seen)

Run via tools/capture.ps1, or:
  mitmdump --mode local:Blaston -s tools/capture_addon.py --set capture_dir=capture/<name> -w capture/<name>/raw.flows

PRIVACY: captures contain your live session tickets / auth tokens. Keep them private.
"""
import base64
import json
import os
import time
from collections import defaultdict

from mitmproxy import ctx, http


def _body(content: bytes | None, content_type: str):
    if content is None:
        return None
    if not content:
        return ""
    try:
        text = content.decode("utf-8")
        if "json" in content_type or text[:1] in "{[":
            try:
                return json.loads(text)
            except ValueError:
                pass
        return text
    except UnicodeDecodeError:
        return {"_base64": base64.b64encode(content).decode()}


class BlastonCapture:
    def __init__(self):
        self.dir = None
        self.endpoints = defaultdict(lambda: [0, set()])

    def load(self, loader):
        loader.add_option("capture_dir", str, "capture/session", "Directory to write capture files to")

    def running(self):
        self.dir = ctx.options.capture_dir
        os.makedirs(os.path.join(self.dir, "by_host"), exist_ok=True)
        ctx.log.info(f"[blaston] writing capture to {os.path.abspath(self.dir)}")

    def _write(self, host: str, rec: dict):
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with open(os.path.join(self.dir, "flows.jsonl"), "a", encoding="utf-8") as f:
            f.write(line)
        safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in host)
        with open(os.path.join(self.dir, "by_host", f"{safe}.jsonl"), "a", encoding="utf-8") as f:
            f.write(line)

    def _summarize(self):
        with open(os.path.join(self.dir, "endpoints.txt"), "w", encoding="utf-8") as f:
            for key, (n, codes) in sorted(self.endpoints.items()):
                f.write(f"{n:5d}  {key}  {sorted(codes)}\n")

    def response(self, flow: http.HTTPFlow):
        req, resp = flow.request, flow.response
        rec = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(flow.request.timestamp_start)),
            "type": "http",
            "method": req.method,
            "url": req.pretty_url,
            "req_headers": dict(req.headers),
            "req_body": _body(req.raw_content and req.get_content(strict=False), req.headers.get("content-type", "")),
            "status": resp.status_code,
            "resp_headers": dict(resp.headers),
            "resp_body": _body(resp.get_content(strict=False), resp.headers.get("content-type", "")),
        }
        self._write(req.pretty_host, rec)
        key = f"{req.method} {req.pretty_host}{req.path.split('?')[0]}"
        self.endpoints[key][0] += 1
        self.endpoints[key][1].add(resp.status_code)
        self._summarize()

    def websocket_message(self, flow: http.HTTPFlow):
        msg = flow.websocket.messages[-1]
        content = msg.content
        rec = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(msg.timestamp)),
            "type": "ws",
            "url": flow.request.pretty_url,
            "dir": "client->server" if msg.from_client else "server->client",
            "body": _body(content, "json" if msg.is_text else ""),
        }
        self._write(flow.request.pretty_host, rec)

    def error(self, flow: http.HTTPFlow):
        rec = {"type": "error", "url": flow.request.pretty_url, "error": str(flow.error)}
        self._write(flow.request.pretty_host, rec)
        ctx.log.warn(f"[blaston] error {flow.request.pretty_url}: {flow.error}")


addons = [BlastonCapture()]
