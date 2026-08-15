#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "runtime"))

from playmac_article_worker import WorkerError, import_macked, import_steam, load_session, login, parse_source, verify_qianfan


DATA_DIR = Path(os.environ.get("PLAYMAC_RUNTIME_DATA", "/data")).resolve()
SESSION_FILE = DATA_DIR / "qianfan-session.json"
JOBS_DIR = DATA_DIR / "jobs"
TOKEN = os.environ.get("PLAYMAC_RUNTIME_TOKEN", "").strip()
PORT = int(os.environ.get("PLAYMAC_RUNTIME_PORT", "8080"))
VERSION = os.environ.get("PLAYMAC_RUNTIME_VERSION", "dev")
OPERATION_LOCK = threading.Lock()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def cleanup_jobs():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 86400
    for path in JOBS_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def execute_import(source, skip_images=False):
    kind, value = parse_source(source)
    if kind == "steam":
        return import_steam(value, str(SESSION_FILE), skip_images)
    return import_macked(value, str(SESSION_FILE), skip_images)


def process_job(job_id, source, skip_images=False):
    path = JOBS_DIR / f"{job_id}.json"
    try:
        with OPERATION_LOCK:
            payload = execute_import(source, skip_images)
        write_json(path, {"success": True, "status": "complete", "payload": payload, "updated_at": int(time.time())})
    except (WorkerError, requests.RequestException) as exc:
        write_json(path, {"success": False, "status": "failed", "error": str(exc), "updated_at": int(time.time())})
    except Exception:
        traceback.print_exc()
        write_json(path, {"success": False, "status": "failed", "error": "文章处理组件发生异常，请查看服务器组件日志。", "updated_at": int(time.time())})


def start_import(source, skip_images=False):
    parse_source(source)
    cleanup_jobs()
    job_id = uuid.uuid4().hex
    write_json(JOBS_DIR / f"{job_id}.json", {"success": True, "status": "running", "created_at": int(time.time())})
    thread = threading.Thread(target=process_job, args=(job_id, source, skip_images), daemon=True)
    thread.start()
    return job_id


def authorized(value):
    if not TOKEN:
        return True
    prefix = "Bearer "
    return value.startswith(prefix) and hmac.compare_digest(value[len(prefix):], TOKEN)


class RuntimeHandler(BaseHTTPRequestHandler):
    server_version = "PlayMacRuntime/1.0"

    def log_message(self, pattern, *args):
        message = pattern % args
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
        sys.stderr.write(f"runtime-request:{digest}\n")

    def send_payload(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_authorization(self):
        if authorized(self.headers.get("Authorization", "")):
            return True
        self.send_payload(401, {"success": False, "error": "服务器组件密钥不正确。"})
        return False

    def read_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 1048576:
            raise WorkerError("请求内容为空或过大。")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkerError("请求格式不正确。") from exc

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_payload(200, {"success": True, "payload": {"status": "ready", "version": VERSION, "qianfan_session": SESSION_FILE.is_file()}})
            return
        if not self.require_authorization():
            return
        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            if not job_id.isalnum() or len(job_id) != 32:
                self.send_payload(400, {"success": False, "error": "任务编号不正确。"})
                return
            result = read_json(JOBS_DIR / f"{job_id}.json")
            if result is None:
                self.send_payload(404, {"success": False, "error": "任务不存在或已过期。"})
                return
            self.send_payload(200, result)
            return
        self.send_payload(404, {"success": False, "error": "接口不存在。"})

    def do_POST(self):
        if not self.require_authorization():
            return
        path = urlparse(self.path).path
        try:
            payload = self.read_payload()
            if path == "/v1/login":
                with OPERATION_LOCK:
                    result = login(str(SESSION_FILE), str(payload.get("email") or ""), str(payload.get("password") or ""))
                self.send_payload(200, {"success": True, "payload": result})
                return
            if path == "/v1/check":
                verify_qianfan(load_session(str(SESSION_FILE)))
                self.send_payload(200, {"success": True, "payload": {"qianfan": "ready"}})
                return
            if path == "/v1/jobs/import":
                job_id = start_import(str(payload.get("source") or ""), bool(payload.get("skip_images")))
                self.send_payload(202, {"success": True, "payload": {"job_id": job_id, "status": "running"}})
                return
            self.send_payload(404, {"success": False, "error": "接口不存在。"})
        except (WorkerError, requests.RequestException) as exc:
            self.send_payload(422, {"success": False, "error": str(exc)})
        except Exception:
            traceback.print_exc()
            self.send_payload(500, {"success": False, "error": "服务器组件发生异常，请查看组件日志。"})


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_jobs()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RuntimeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
