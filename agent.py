"""
blocker_video_safe_with_logs.py

Improved VideoBlockerSafe mitmproxy addon.

Main improvements vs original:
- Uses urllib ProxyHandler({}) to ignore system proxy env vars for blocklist fetches.
- Caches the blocklist for reload_interval seconds (defaults to 30s).
- Retries fetches with exponential backoff (configurable).
- Keeps previously loaded rules if fetch fails (safe default).
- Adds a simple lock for counters/log writes to reduce race conditions.
- Stores all logs in a single file (no daily rotation).
"""

from mitmproxy import http, ctx
from urllib.parse import urlparse, parse_qs
import time
import os
import re
import json
import urllib.request
import urllib.error
import threading

# --- Configuration ---
BLOCKLIST_URL = "http://192.168.1.189/url_blocklist.txt"
LOG_PATH = r"C:\url-block\logs.json"  # can be absolute or relative
REQUEST_TIMEOUT = 10
DEBUG = True

# cache/retry settings
RELOAD_INTERVAL = 30        # seconds between blocklist fetch attempts (default 30s)
MAX_RETRIES = 2             # number of retry attempts on fetch failure
RETRY_BACKOFF = 1.5         # exponential backoff multiplier

# CDN hosts we treat conservatively. Add more as necessary.
SUSPICIOUS_CDN_HOSTS = ("googlevideo.com", "ytimg.com")
# -------------------------

def make_response(status: int, body: bytes, headers: dict):
    # Compatibility across mitmproxy versions
    factory = None
    if hasattr(http, "Response"):
        factory = getattr(http, "Response")
    elif hasattr(http, "HTTPResponse"):
        factory = getattr(http, "HTTPResponse")
    else:
        raise RuntimeError("mitmproxy http.Response/HTTPResponse factory not found")
    if hasattr(factory, "make"):
        return factory.make(status, body, headers)
    return factory(status, body, headers)

class VideoBlockerSafe:
    def __init__(self):
        self.block_vids = set()
        self.block_prefixes = []
        self.block_hosts = set()
        self._last_modified_header = None

        # counters and locking
        self.counters = {
            "blocked_watch": 0,
            "blocked_cdn_referer": 0,
            "blocked_api": 0,
            "blocked_host": 0,
            "blocked_prefix": 0,
            "blocked_regex": 0,
            "allowed": 0,
        }
        self._lock = threading.Lock()

        # reload / retry bookkeeping
        self._last_load_time = 0
        self._reload_interval = RELOAD_INTERVAL
        self._max_retries = MAX_RETRIES
        self._retry_backoff = RETRY_BACKOFF

        # initial load (best effort)
        try:
            self._load_blocklist(force=True)
        except Exception:
            ctx.log.warn("VideoBlockerSafe: initial blocklist load failed (continuing)")

    # helper to get log path (no daily rotation)
    def _get_log_path(self):
        if os.path.isabs(LOG_PATH):
            return LOG_PATH
        else:
            return os.path.join(os.path.dirname(__file__), LOG_PATH)

    def _write_log_line(self, payload: dict):
        log_path = self._get_log_path()
        parent_dir = os.path.dirname(log_path)
        try:
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            ctx.log.warn(f"VideoBlockerSafe: failed to create log directory {parent_dir}: {e}")

        try:
            # Acquire lock to avoid interleaved writes/counters updates
            with self._lock:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            ctx.log.warn(f"VideoBlockerSafe: failed to write log file {log_path}: {e}")
            try:
                ctx.log.info("VideoBlockerSafe (fallback log): " + json.dumps(payload, default=str))
            except Exception:
                ctx.log.info("VideoBlockerSafe: failed to stringify payload for fallback log")

    def _emit_log(self, flow, event_type: str, blocked: bool = False, extra: dict = None):
        if extra is None:
            extra = {}
        req = flow.request
        parsed = urlparse(req.pretty_url) if req else None
        client_ip, client_port = self._client_address(flow)
        try:
            headers = {k: v for k, v in req.headers.items()} if req and req.headers else {}
        except Exception:
            headers = {}
        payload = {
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "event": event_type,
            "client_ip": client_ip,
            "client_port": client_port,
            "host": parsed.hostname if parsed else (req.host if req else None),
            "url": req.pretty_url if req else None,
            "method": req.method if req else None,
            "path": parsed.path if parsed else None,
            "query": parse_qs(parsed.query) if parsed else {},
            "http_version": getattr(req, "http_version", None),
            "headers": headers,
            "user_agent": req.headers.get("user-agent") if req else None,
            "referer": req.headers.get("referer") if req else None,
            "content_length": len(req.raw_content) if req and getattr(req, "raw_content", None) is not None else (len(req.content) if req and getattr(req, "content", None) is not None else None),
            "blocked": bool(blocked),
            "counters_snapshot": dict(self.counters),
        }
        payload.update(extra)
        # write (thread-safe)
        self._write_log_line(payload)

    def _client_address(self, flow):
        try:
            addr = flow.client_conn.address
            if isinstance(addr, (list, tuple)) and len(addr) >= 2:
                return addr[0], addr[1]
        except Exception:
            pass
        try:
            peer = getattr(flow.client_conn, "peername", None)
            if isinstance(peer, (list, tuple)) and len(peer) >= 2:
                return peer[0], peer[1]
        except Exception:
            pass
        return None, None

    def _load_blocklist(self, force=False):
        """
        Fetch blocklist from BLOCKLIST_URL. Uses a ProxyHandler({}) to avoid system proxies.
        Caches results for self._reload_interval seconds unless force=True.
        Keeps previous lists on failure.
        """
        now = time.time()
        if not force and (now - getattr(self, "_last_load_time", 0)) < self._reload_interval:
            # skip reload (cached)
            return
        self._last_load_time = now

        attempt = 0
        while attempt <= self._max_retries:
            attempt += 1
            try:
                req = urllib.request.Request(BLOCKLIST_URL, headers={"User-Agent": "VideoBlockerSafe/1.0"})
                if self._last_modified_header:
                    req.add_header("If-Modified-Since", self._last_modified_header)

                # Use an opener that ignores environment proxies (prevents proxy loops)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                ctx.log.debug(f"VideoBlockerSafe: fetching blocklist attempt {attempt} from {BLOCKLIST_URL}")
                with opener.open(req, timeout=REQUEST_TIMEOUT) as response:
                    new_last_modified = response.headers.get("Last-Modified")
                    if new_last_modified:
                        self._last_modified_header = new_last_modified
                    content = response.read().decode("utf-8", errors="ignore")
                    lines = content.splitlines()

                # parse into temporary structures
                new_vids = set()
                new_prefixes = []
                new_hosts = set()

                for raw in lines:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("vid:"):
                        vid = line.split(":", 1)[1].strip()
                        if vid:
                            new_vids.add(vid)
                    elif line.startswith("re:"):
                        try:
                            cre = re.compile(line.split(":", 1)[1].strip())
                            new_prefixes.append(("__regex__", cre))
                        except re.error:
                            ctx.log.warn("VideoBlockerSafe: invalid regex in blocklist: %s" % line)
                    else:
                        if "/" in line:
                            host_part, path_part = line.split("/", 1)
                            host_part = host_part.strip()
                            path_prefix = "/" + path_part.strip()
                            new_prefixes.append((host_part, path_prefix))
                        else:
                            new_hosts.add(line.strip())

                # atomically replace in-memory lists
                with self._lock:
                    self.block_vids = new_vids
                    self.block_prefixes = new_prefixes
                    self.block_hosts = new_hosts

                ctx.log.info("VideoBlockerSafe: loaded blocklist. vids=%d prefixes=%d hosts=%d" %
                             (len(self.block_vids), len(self.block_prefixes), len(self.block_hosts)))
                if DEBUG:
                    ctx.log.info("block vids: %s" % (", ".join(sorted(list(self.block_vids))[:20]) or "<none>"))
                return

            except urllib.error.HTTPError as e:
                if e.code == 304:
                    ctx.log.debug("VideoBlockerSafe: blocklist not modified (304).")
                    return
                ctx.log.warn(f"VideoBlockerSafe: HTTPError fetching blocklist: {e} (code {getattr(e,'code',None)})")
            except urllib.error.URLError as e:
                ctx.log.warn(f"VideoBlockerSafe: URLError fetching blocklist: {getattr(e,'reason',e)}")
            except Exception as e:
                ctx.log.warn(f"VideoBlockerSafe: unexpected error fetching blocklist: {e}")

            # backoff before retry, unless we've exhausted attempts
            if attempt <= self._max_retries:
                backoff = (self._retry_backoff ** attempt)
                ctx.log.debug(f"VideoBlockerSafe: retrying blocklist fetch in {backoff:.1f}s (attempt {attempt}/{self._max_retries})")
                time.sleep(backoff)
            else:
                ctx.log.warn("VideoBlockerSafe: exhausted retries for blocklist fetch, keeping previous rules.")
                return

    def _is_watch_path(self, path: str):
        # Normalized check for YouTube watch path
        return path == "/watch" or path.startswith("/watch/") or path.startswith("/watch?")

    def _blocked_response(self, flow, reason="blocked"):
        accept = flow.request.headers.get("accept", "")
        body_html = "<html><body><h1>Blocked</h1><p>Request blocked by CyberSentinel: %s</p></body></html>" % (reason,)
        if "application/json" in accept:
            body = json.dumps({"error": "blocked", "reason": reason}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        else:
            body = body_html.encode("utf-8")
            headers = {"Content-Type": "text/html; charset=utf-8"}
        flow.response = make_response(403, body, headers)

    def request(self, flow: http.HTTPFlow):
        # Rate-limited blocklist reload
        self._load_blocklist()

        req = flow.request
        if not req:
            return
        parsed = urlparse(req.pretty_url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
        query = parse_qs(parsed.query or "")

        # 1) /watch?v=VIDEOID immediate block based on vid list
        if self._is_watch_path(path):
            vlist = query.get("v", [])
            if vlist and vlist[0] in self.block_vids:
                vid = vlist[0]
                with self._lock:
                    self.counters["blocked_watch"] += 1
                ctx.log.warn(f"VideoBlockerSafe: blocked watch page vid={vid} url={req.pretty_url}")
                extra = {"block_type": "watch", "matched_vid": vid, "in_blocklist": True}
                self._emit_log(flow, "blocked_watch", blocked=True, extra=extra)
                self._blocked_response(flow, reason=f"video id {vid} blocked")
                return

        # 2) YouTube API endpoints - try robust detection (JSON parse fallback to substring)
        if host.endswith("youtube.com") and ("/youtubei/v1/player" in path or "/youtubei/v1/next" in path):
            try:
                if req.content:
                    ctype = req.headers.get("content-type", "")
                    body = req.content.decode("utf-8", errors="ignore")
                    found_vid = None
                    # best-effort JSON parse when content-type suggests JSON
                    if "application/json" in ctype:
                        try:
                            parsed_json = json.loads(body)
                            # recursively search parsed_json for any key 'videoId'
                            stack = [parsed_json]
                            while stack:
                                node = stack.pop()
                                if isinstance(node, dict):
                                    for k, v in node.items():
                                        if k == "videoId":
                                            if isinstance(v, str) and v in self.block_vids:
                                                found_vid = v
                                                break
                                        else:
                                            stack.append(v)
                                elif isinstance(node, list):
                                    for item in node:
                                        stack.append(item)
                                if found_vid:
                                    break
                        except Exception:
                            # fall back to substring check below
                            pass
                    # fallback substring matching (covers other content-types or malformed JSON)
                    if not found_vid:
                        for vid in self.block_vids:
                            if f"\"videoId\":\"{vid}\"" in body or f"'videoId':'{vid}'" in body or f'"videoId": "{vid}"' in body:
                                found_vid = vid
                                break

                    if found_vid:
                        with self._lock:
                            self.counters["blocked_api"] += 1
                        ctx.log.warn(f"VideoBlockerSafe: blocked API call vid={found_vid} url={req.pretty_url}")
                        extra = {"block_type": "youtube_api", "matched_vid": found_vid, "in_blocklist": True}
                        self._emit_log(flow, "blocked_api", blocked=True, extra=extra)
                        self._blocked_response(flow, reason=f"api video id {found_vid} blocked")
                        return
            except Exception as e:
                ctx.log.debug(f"VideoBlockerSafe: API body parse failed: {e}")

        # 3) CDN hosts - only block when referer contains a blocked v=
        if any(host.endswith(p) for p in SUSPICIOUS_CDN_HOSTS):
            referer = req.headers.get("referer", "")
            if referer:
                try:
                    rps = urlparse(referer)
                    rquery = parse_qs(rps.query or "")
                    rv = rquery.get("v", [])
                    if rv and rv[0] in self.block_vids:
                        vid = rv[0]
                        with self._lock:
                            self.counters["blocked_cdn_referer"] += 1
                        ctx.log.warn(f"VideoBlockerSafe: blocked CDN request via Referer vid={vid} host={host} url={req.pretty_url}")
                        extra = {"block_type": "cdn_referer", "matched_vid": vid, "referer": referer, "in_blocklist": True}
                        self._emit_log(flow, "blocked_cdn_referer", blocked=True, extra=extra)
                        self._blocked_response(flow, reason=f"cdn for video id {vid} blocked (referer)")
                        return
                except Exception:
                    ctx.log.debug("VideoBlockerSafe: referer parse failed, allowing CDN request")
            # allowed CDN request
            with self._lock:
                self.counters["allowed"] += 1
            self._emit_log(flow, "allowed_cdn", blocked=False, extra={"note": "cdn request allowed (no blocked referer)"})
            return

        # 4) host-only block rules
        for bh in list(self.block_hosts):
            if host == bh or host.endswith("." + bh):
                with self._lock:
                    self.counters["blocked_host"] += 1
                ctx.log.warn(f"VideoBlockerSafe: blocked by host-only rule host={host} url={req.pretty_url}")
                extra = {"block_type": "host", "block_rule": bh, "in_blocklist": True}
                self._emit_log(flow, "blocked_host", blocked=True, extra=extra)
                self._blocked_response(flow, reason=f"host {host} blocked")
                return

        # 5) prefix and regex rules
        for entry in list(self.block_prefixes):
            if entry[0] == "__regex__":
                cre = entry[1]
                try:
                    if cre.search(req.pretty_url):
                        with self._lock:
                            self.counters["blocked_regex"] += 1
                        ctx.log.warn(f"VideoBlockerSafe: blocked by regex {cre.pattern} url={req.pretty_url}")
                        extra = {"block_type": "regex", "pattern": cre.pattern, "in_blocklist": True}
                        self._emit_log(flow, "blocked_regex", blocked=True, extra=extra)
                        self._blocked_response(flow, reason="regex rule matched")
                        return
                except re.error:
                    ctx.log.warn("VideoBlockerSafe: regex error while testing pattern")
            else:
                host_part, path_prefix = entry
                if (host == host_part or host.endswith("." + host_part)) and path.startswith(path_prefix):
                    with self._lock:
                        self.counters["blocked_prefix"] += 1
                    ctx.log.warn(f"VideoBlockerSafe: blocked by prefix {host_part}{path_prefix} url={req.pretty_url}")
                    extra = {"block_type": "prefix", "rule": f"{host_part}{path_prefix}", "in_blocklist": True}
                    self._emit_log(flow, "blocked_prefix", blocked=True, extra=extra)
                    self._blocked_response(flow, reason=f"prefix rule {host_part}{path_prefix}")
                    return

        # default: allowed
        with self._lock:
            self.counters["allowed"] += 1
        self._emit_log(flow, "allowed", blocked=False, extra={})

    def response(self, flow: http.HTTPFlow):
        parsed = urlparse(flow.request.pretty_url)
        if parsed.path == "/__blocker_stats":
            stats = {
                "counts": self.counters,
                "blocked_vids": sorted(list(self.block_vids))
            }
            flow.response = make_response(200, json.dumps(stats, indent=2).encode("utf-8"),
                                          {"Content-Type": "application/json"})
            return

addons = [
    VideoBlockerSafe()
]