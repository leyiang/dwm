#!/usr/bin/env python3
"""CLI helper for talking to a running dwmshell instance (also handy for Agents)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def req(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Control dwmshell desktop widgets")
    p.add_argument("--port", type=int, default=17777)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List active widgets")
    sub.add_parser("reload", help="Trigger immediate widget rescan")

    p_push = sub.add_parser("push", help="Create or update a widget dynamically")
    p_push.add_argument("id", help="Widget id (alphanumeric, -, _)")
    p_push.add_argument("--html", help="Inline HTML string")
    p_push.add_argument("--html-file", type=Path, help="Read HTML from file")
    p_push.add_argument("--x", type=int)
    p_push.add_argument("--y", type=int)
    p_push.add_argument("--width", type=int)
    p_push.add_argument("--height", type=int)
    p_push.add_argument("--title")
    p_push.add_argument("--data", help="Initial JSON data string")

    p_data = sub.add_parser("data", help="Push live JSON data to a widget")
    p_data.add_argument("id")
    p_data.add_argument("json_data", help="JSON payload string")

    p_rm = sub.add_parser("remove", help="Remove or disable a widget")
    p_rm.add_argument("id")

    args = p.parse_args()

    if args.cmd == "list":
        code, out = req(args.port, "GET", "/api/widgets")
    elif args.cmd == "reload":
        code, out = req(args.port, "POST", "/api/reload", {})
    elif args.cmd == "push":
        payload: dict = {}
        if args.html_file:
            payload["html"] = args.html_file.read_text(encoding="utf-8")
        elif args.html is not None:
            payload["html"] = args.html
        for k in ("x", "y", "width", "height", "title"):
            v = getattr(args, k)
            if v is not None:
                payload[k] = v
        if args.data is not None:
            payload["data"] = json.loads(args.data)
        code, out = req(args.port, "POST", f"/api/widgets/{urllib.parse.quote(args.id)}", payload)
    elif args.cmd == "data":
        payload = json.loads(args.json_data)
        code, out = req(args.port, "POST", f"/api/widgets/{urllib.parse.quote(args.id)}/data", payload)
    elif args.cmd == "remove":
        code, out = req(args.port, "DELETE", f"/api/widgets/{urllib.parse.quote(args.id)}")
    else:
        sys.exit(2)

    print(out)
    sys.exit(0 if 200 <= code < 300 else 1)


if __name__ == "__main__":
    main()
