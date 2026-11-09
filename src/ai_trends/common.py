"""Immutable HTTP snapshots, conservative caching and interoperable file IO."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    if isinstance(data, Path):
        h = hashlib.sha256()
        with data.open('rb') as f:
            for block in iter(lambda: f.read(1048576), b''):
                h.update(block)
        return h.hexdigest()
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    if isinstance(data, str):
        data = data.encode('utf-8')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read_json(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def write_jsonl(path, rows):
    atomic_write(path, ''.join(json.dumps(x, ensure_ascii=False, allow_nan=False) + '\n' for x in rows))


def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().split('\n') if x.strip()] if Path(path).exists() else []


def write_csv(path, rows, fields=None):
    import io
    rows = list(rows)
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for r in rows:
        cooked = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()}
        # Keep stored values literal; quote spreadsheet formula prefixes for safe opening.
        cooked = {k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v) for k, v in cooked.items()}
        writer.writerow(cooked)
    atomic_write(path, '\ufeff' + buffer.getvalue())


def safe_url(url):
    try:
        p = urlparse(url or '')
        return url if p.scheme in ('https', 'http') and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''


class FetchError(RuntimeError):
    def __init__(self, message, status=None, challenge=False):
        super().__init__(message)
        self.status = status
        self.challenge = challenge


class HttpClient:
    """GET-only public client. Errors are audited but never successful caches."""
    def __init__(self, output, config=None):
        self.output = Path(output)
        self.root = self.output / 'raw/http'
        self.root.mkdir(parents=True, exist_ok=True)
        self.cfg = config or {}
        self._locks = {}
        self._guard = threading.Lock()
        self._last = {}
        self._local = threading.local()

    def _open(self, req):
        if not self.cfg.get('connection_pool'):
            return urlopen(req, timeout=self.cfg.get('timeout',35))
        # An optional transport optimization; snapshot/error semantics are identical.
        import io
        import requests
        session=getattr(self._local,'session',None)
        if session is None:
            session=requests.Session()
            self._local.session=session
        response=session.get(req.full_url,headers=dict(req.header_items()),timeout=self.cfg.get('timeout',35))
        if response.status_code>=400:
            raise HTTPError(req.full_url,response.status_code,response.reason,response.headers,io.BytesIO(response.content))
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):response.close()
            url=response.url
            status=response.status_code
            headers=response.headers
            def read(self):return response.content
        return Response()

    def fetch(self, url, refresh=False):
        if not safe_url(url):
            raise FetchError('Unsafe URL')
        key = sha256(url)
        mp, bp = self.root / (key + '.json'), self.root / (key + '.body.gz')
        meta = read_json(mp)
        if meta and meta.get('status') == 'success' and not refresh:
            body = gzip.decompress(bp.read_bytes())
            if sha256(body) != meta['sha256']:
                raise FetchError('Cached snapshot hash mismatch')
            return body, meta
        host = urlparse(url).netloc
        with self._guard:
            lock = self._locks.setdefault(host, threading.Lock())
        for attempt in range(self.cfg.get('retries', 2) + 1):
            with lock:
                time.sleep(max(0, self.cfg.get('min_interval', .35) - (time.monotonic() - self._last.get(host, 0))))
                self._last[host] = time.monotonic()
            now = utcnow()
            try:
                req = Request(url, headers={'User-Agent': 'AuditableAITrends/1.0 (public academic metadata research)', 'Accept-Encoding': 'identity'})
                with self._open(req) as response:
                    body = response.read()
                    final, status = response.url, response.status
                    content_type = response.headers.get('Content-Type', '')
                prefix = body[:20000].lower()
                is_html = 'text/html' in content_type or prefix.lstrip().startswith((b'<!doctype html',b'<html'))
                challenge = (b'challengerequirederror' in prefix or (is_html and any(x in prefix for x in (b'<title>just a moment', b'cf-chl-', b'cf-turnstile', b'<title>verify you are human'))))
                if not body or challenge:
                    raise FetchError('Empty response or platform verification', status, challenge)
                meta = {'url': url, 'final_url': final, 'collected_at': now, 'http_status': status, 'status': 'success', 'size_bytes': len(body), 'sha256': sha256(body), 'content_type': content_type, 'body_path': str(bp.relative_to(self.output))}
                # Never overwrite a prior successful response: refresh gets its own dated path.
                if mp.exists() and read_json(mp, {}).get('status') == 'success' and refresh:
                    stamp = now.replace(':','').replace('.','')
                    mp = self.root / f'{key}-{stamp}.json'
                    bp = self.root / f'{key}-{stamp}.body.gz'
                    meta['body_path'] = str(bp.relative_to(self.output))
                atomic_write(bp, gzip.compress(body, mtime=0))
                write_json(mp, meta)
                self._log(meta)
                return body, meta
            except Exception as e:
                status = getattr(e, 'code', getattr(e, 'status', None))
                err_body = b''
                if isinstance(e, HTTPError):
                    err_body = e.read()
                challenge = getattr(e, 'challenge', False) or status in (401,403) or b'ChallengeRequiredError' in err_body
                info = {'url': url, 'collected_at': now, 'status': 'blocked' if challenge else 'failed', 'http_status': status, 'error': str(e), 'attempt': attempt, 'error_body_sha256': sha256(err_body)}
                if err_body:
                    ep = self.root / f'{key}.error-{attempt}.body.gz'
                    atomic_write(ep, gzip.compress(err_body, mtime=0))
                    info['error_body_path'] = str(ep.relative_to(self.output))
                self._log(info)
                if not meta or meta.get('status') != 'success':
                    write_json(mp, info)
                if challenge or status in (400,404,410) or attempt == self.cfg.get('retries', 2):
                    raise FetchError(str(e), status, challenge) from e
                time.sleep(min(4, 2**attempt))

    def _log(self, item):
        with self._guard:
            path = self.output / 'collection_log.jsonl'
            with path.open('a') as f:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
