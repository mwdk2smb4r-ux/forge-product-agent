from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit


ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SAFE_CHARSETS = {"ascii", "iso-8859-1", "utf-8", "windows-1252"}
GITHUB_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
GIT_REF = re.compile(r"[A-Za-z0-9._/-]{1,200}\Z")
HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


class ResearchError(ValueError):
    pass


@dataclass(frozen=True)
class HTTPResult:
    url: str
    status: int
    content_type: str
    charset: str
    body: bytes


class _TextExtractor(HTMLParser):
    BLOCKS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    HIDDEN = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.HIDDEN:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.HIDDEN and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


class SafeHTTPSClient:
    """Bounded HTTPS client that pins a validated public DNS result per request."""

    def __init__(
        self,
        timeout_seconds: int,
        max_response_bytes: int,
        max_redirects: int,
        allowed_domains: tuple[str, ...] = (),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.allowed_domains = tuple(domain.lower().rstrip(".") for domain in allowed_domains)
        self.ssl_context = ssl.create_default_context()

    def _validated_url(self, url: str) -> tuple[str, str, int, str]:
        if not isinstance(url, str) or not url or len(url) > 2048 or "\x00" in url:
            raise ResearchError("URL must be a non-empty string no longer than 2048 characters")
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ResearchError("research URLs must use public HTTPS")
        if parsed.username or parsed.password:
            raise ResearchError("URL credentials are not allowed")
        try:
            port = parsed.port or 443
        except ValueError:
            raise ResearchError("URL port is invalid") from None
        if port != 443:
            raise ResearchError("research URLs must use HTTPS port 443")
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError:
            raise ResearchError("URL hostname is invalid") from None
        if not host or len(host) > 253 or host == "localhost" or host.endswith(".local"):
            raise ResearchError("URL hostname is not public")
        if self.allowed_domains and not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
            raise ResearchError("URL hostname is not in research.allowed_domains")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            raise ResearchError("IP-literal URLs are denied; use a public hostname")
        if not HOSTNAME.fullmatch(host) or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            for label in host.split(".")
        ):
            raise ResearchError("URL hostname is invalid")
        path = parsed.path or "/"
        target = urlunsplit(("", "", path, parsed.query, ""))
        normalized = urlunsplit(("https", host, path, parsed.query, ""))
        return normalized, host, port, target

    @staticmethod
    def _public_addresses(host: str, port: int) -> list[tuple[int, int, int, tuple[Any, ...]]]:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ResearchError(f"hostname could not be resolved: {exc}") from None
        public: list[tuple[int, int, int, tuple[Any, ...]]] = []
        seen: set[tuple[int, str]] = set()
        for family, socktype, proto, _canonname, sockaddr in answers:
            address_text = str(sockaddr[0])
            try:
                address = ipaddress.ip_address(address_text)
            except ValueError:
                raise ResearchError("DNS returned an invalid address") from None
            if not address.is_global:
                raise ResearchError("DNS resolved to a private, local, reserved, or non-global address")
            marker = (family, address_text)
            if marker not in seen:
                seen.add(marker)
                public.append((family, socktype, proto, sockaddr))
        if not public:
            raise ResearchError("hostname did not resolve to a public address")
        return public

    @staticmethod
    def _pinned_connection(address: tuple[int, int, int, tuple[Any, ...]], timeout: float | None, source: Any = None):
        family, socktype, proto, sockaddr = address
        connection = socket.socket(family, socktype, proto)
        try:
            if timeout is not None:
                connection.settimeout(timeout)
            if source:
                connection.bind(source)
            connection.connect(sockaddr)
            return connection
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ResearchError("HTTPS request exceeded the configured time limit")
        return remaining

    def _read_bounded(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPSConnection,
        deadline: float,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while total <= self.max_response_bytes:
            remaining = self._remaining(deadline)
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read(min(65_536, self.max_response_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        payload = b"".join(chunks)
        if len(payload) > self.max_response_bytes:
            raise ResearchError("response exceeds the configured byte limit")
        return payload

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        allow_redirects: bool = True,
    ) -> HTTPResult:
        current = url
        deadline = time.monotonic() + self.timeout_seconds
        request_headers = {
            "Accept": "text/html,text/plain,text/markdown,application/json,application/xml;q=0.8",
            "Accept-Encoding": "identity",
            "User-Agent": "forge-product-agent/0.2 (+https://github.com/mwdk2smb4r-ux/forge-product-agent)",
        }
        if headers:
            request_headers.update(headers)
        for redirect_count in range(self.max_redirects + 1):
            normalized, host, port, target = self._validated_url(current)
            addresses = self._public_addresses(host, port)
            connection = http.client.HTTPSConnection(
                host,
                port,
                timeout=self._remaining(deadline),
                context=self.ssl_context,
            )
            connection._create_connection = lambda _address, timeout=None, source_address=None, pinned=addresses[0]: (  # type: ignore[attr-defined]
                self._pinned_connection(pinned, timeout, source_address)
            )
            try:
                connection.request(method, target, body=body, headers=request_headers)
                if connection.sock is not None:
                    connection.sock.settimeout(self._remaining(deadline))
                response = connection.getresponse()
                if response.status in REDIRECT_STATUSES:
                    if not allow_redirects:
                        raise ResearchError("redirects are not allowed for this endpoint")
                    location = response.getheader("Location")
                    if not location or redirect_count >= self.max_redirects:
                        raise ResearchError("redirect limit reached or redirect location missing")
                    current = urljoin(normalized, location)
                    method = "GET"
                    body = None
                    request_headers.pop("Authorization", None)
                    request_headers.pop("Content-Type", None)
                    continue
                if not 200 <= response.status < 300:
                    raise ResearchError(f"remote server returned HTTP {response.status}")
                encoding = (response.getheader("Content-Encoding") or "identity").lower()
                if encoding != "identity":
                    raise ResearchError("compressed responses are not accepted")
                length = response.getheader("Content-Length")
                if length:
                    try:
                        if int(length) > self.max_response_bytes:
                            raise ResearchError("response exceeds the configured byte limit")
                    except ValueError:
                        raise ResearchError("response Content-Length is invalid") from None
                content_type = response.headers.get_content_type().lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise ResearchError(f"unsupported response content type: {content_type}")
                charset = (response.headers.get_content_charset() or "utf-8").lower()
                if charset not in SAFE_CHARSETS:
                    raise ResearchError(f"unsupported response charset: {charset}")
                payload = self._read_bounded(response, connection, deadline)
                return HTTPResult(normalized, response.status, content_type, charset, payload)
            except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
                raise ResearchError(f"HTTPS request failed: {exc}") from None
            finally:
                connection.close()
        raise ResearchError("redirect limit reached")


class Research:
    def __init__(
        self,
        timeout_seconds: int,
        max_response_bytes: int,
        max_redirects: int,
        allowed_domains: tuple[str, ...],
        search_provider: str,
        search_api_key: str,
    ) -> None:
        self.fetch_client = SafeHTTPSClient(timeout_seconds, max_response_bytes, max_redirects, allowed_domains)
        self.service_client = SafeHTTPSClient(timeout_seconds, max_response_bytes, 0)
        self.max_response_bytes = max_response_bytes
        self.search_provider = search_provider
        self.search_api_key = search_api_key

    @staticmethod
    def _decoded_text(result: HTTPResult) -> str:
        return result.body.decode(result.charset, errors="replace").replace("\x00", "")

    @staticmethod
    def _bounded_text(text: str, max_chars: int) -> tuple[str, bool]:
        limit = max(1_000, min(int(max_chars), 50_000))
        return (text[:limit], len(text) > limit)

    def fetch_url(self, url: str, max_chars: int = 20_000) -> dict[str, Any]:
        result = self.fetch_client.request(url)
        decoded = self._decoded_text(result)
        if result.content_type in {"text/html", "application/xhtml+xml"}:
            parser = _TextExtractor()
            parser.feed(decoded)
            decoded = parser.text()
        content, truncated = self._bounded_text(decoded, max_chars)
        return {
            "source_url": result.url,
            "status": result.status,
            "content_type": result.content_type,
            "sha256": hashlib.sha256(result.body).hexdigest(),
            "content": content,
            "truncated": truncated,
        }

    @staticmethod
    def _domain_filter(domains: list[str] | None) -> list[str]:
        if domains is None:
            return []
        if not isinstance(domains, list) or len(domains) > 10:
            raise ResearchError("domains must be an array of at most 10 hostnames")
        clean: list[str] = []
        for value in domains:
            if not isinstance(value, str):
                raise ResearchError("domains must contain only strings")
            domain = value.strip().lower().rstrip(".")
            if not domain or len(domain) > 253 or any(character in domain for character in "/:* "):
                raise ResearchError(f"invalid search domain: {value}")
            try:
                ascii_domain = domain.encode("idna").decode("ascii")
            except UnicodeError:
                raise ResearchError(f"invalid search domain: {value}") from None
            if not HOSTNAME.fullmatch(ascii_domain) or any(
                not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                for label in ascii_domain.split(".")
            ):
                raise ResearchError(f"invalid search domain: {value}")
            clean.append(ascii_domain)
        return clean

    def search_web(
        self,
        query: str,
        max_results: int = 5,
        domains: list[str] | None = None,
        recency: str = "",
    ) -> dict[str, Any]:
        if self.search_provider == "none":
            raise ResearchError("web search is disabled; direct URL and public GitHub research remain available")
        if self.search_provider != "perplexity":
            raise ResearchError("unsupported search provider")
        if not self.search_api_key:
            raise ResearchError("PERPLEXITY_API_KEY is not set; direct URL and public GitHub research remain available")
        if not isinstance(query, str) or not query.strip() or len(query) > 500 or "\x00" in query:
            raise ResearchError("query must contain 1 to 500 characters")
        result_limit = max(1, min(int(max_results), 10))
        if recency not in {"", "hour", "day", "week", "month", "year"}:
            raise ResearchError("recency must be empty, hour, day, week, month, or year")
        payload: dict[str, Any] = {
            "query": query.strip(),
            "max_results": result_limit,
            "max_tokens": min(10_000, result_limit * 1_500),
            "max_tokens_per_page": 1_500,
        }
        clean_domains = self._domain_filter(domains)
        if clean_domains:
            payload["search_domain_filter"] = clean_domains
        if recency:
            payload["search_recency_filter"] = recency
        response = self.service_client.request(
            "https://api.perplexity.ai/search",
            method="POST",
            headers={
                "Authorization": f"Bearer {self.search_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            allow_redirects=False,
        )
        try:
            data = json.loads(self._decoded_text(response))
        except json.JSONDecodeError:
            raise ResearchError("search provider returned invalid JSON") from None
        results: list[dict[str, str]] = []
        for item in data.get("results", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict) or len(results) >= result_limit:
                continue
            url = str(item.get("url") or "")
            try:
                self.service_client._validated_url(url)
            except ResearchError:
                continue
            results.append(
                {
                    "title": str(item.get("title") or "")[:500],
                    "url": url[:2048],
                    "snippet": str(item.get("snippet") or "")[:2_000],
                    "date": str(item.get("date") or "")[:100],
                    "last_updated": str(item.get("last_updated") or "")[:100],
                }
            )
        return {"provider": "perplexity", "query": query.strip(), "results": results}

    @staticmethod
    def _github_name(value: str, label: str) -> str:
        if not isinstance(value, str) or not GITHUB_NAME.fullmatch(value) or value in {".", ".."}:
            raise ResearchError(f"invalid GitHub {label}")
        return value

    @staticmethod
    def _github_path(value: str) -> str:
        if not isinstance(value, str) or len(value) > 500 or "\x00" in value or "\\" in value:
            raise ResearchError("invalid GitHub path")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ResearchError("GitHub path must be relative and cannot contain '..'")
        return str(path) if str(path) != "." else ""

    @staticmethod
    def _github_ref(value: str) -> str:
        if not value:
            return ""
        if not isinstance(value, str) or not GIT_REF.fullmatch(value) or ".." in value or "@{" in value:
            raise ResearchError("invalid GitHub ref")
        return value

    def _github_json(self, endpoint: str) -> Any:
        response = self.service_client.request(
            f"https://api.github.com{endpoint}",
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        try:
            return json.loads(self._decoded_text(response))
        except json.JSONDecodeError:
            raise ResearchError("GitHub returned invalid JSON") from None

    def github_read(
        self,
        owner: str,
        repo: str,
        operation: str = "contents",
        path: str = "",
        ref: str = "",
        max_entries: int = 50,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        owner = self._github_name(owner, "owner")
        repo = self._github_name(repo, "repository")
        if operation not in {"contents", "repository", "releases"}:
            raise ResearchError("operation must be contents, repository, or releases")
        entry_limit = max(1, min(int(max_entries), 100))
        base = f"/repos/{quote(owner)}/{quote(repo)}"
        if operation == "repository":
            data = self._github_json(base)
            if not isinstance(data, dict):
                raise ResearchError("GitHub returned an invalid repository response")
            license_data = data.get("license") if isinstance(data.get("license"), dict) else {}
            return {
                "operation": operation,
                "full_name": str(data.get("full_name") or ""),
                "description": str(data.get("description") or "")[:2_000],
                "html_url": str(data.get("html_url") or ""),
                "default_branch": str(data.get("default_branch") or ""),
                "license": str(license_data.get("spdx_id") or ""),
                "archived": bool(data.get("archived")),
                "fork": bool(data.get("fork")),
                "updated_at": str(data.get("updated_at") or ""),
            }
        if operation == "releases":
            data = self._github_json(f"{base}/releases?{urlencode({'per_page': entry_limit})}")
            if not isinstance(data, list):
                raise ResearchError("GitHub returned an invalid releases response")
            return {
                "operation": operation,
                "releases": [
                    {
                        "name": str(item.get("name") or "")[:500],
                        "tag": str(item.get("tag_name") or "")[:200],
                        "html_url": str(item.get("html_url") or ""),
                        "published_at": str(item.get("published_at") or ""),
                        "draft": bool(item.get("draft")),
                        "prerelease": bool(item.get("prerelease")),
                    }
                    for item in data[:entry_limit]
                    if isinstance(item, dict)
                ],
            }
        clean_path = self._github_path(path)
        clean_ref = self._github_ref(ref)
        endpoint = f"{base}/contents"
        if clean_path:
            endpoint += f"/{quote(clean_path, safe='/')}"
        if clean_ref:
            endpoint += f"?{urlencode({'ref': clean_ref})}"
        data = self._github_json(endpoint)
        if isinstance(data, list):
            return {
                "operation": operation,
                "path": clean_path,
                "entries": [
                    {
                        "name": str(item.get("name") or "")[:500],
                        "path": str(item.get("path") or "")[:1_000],
                        "type": str(item.get("type") or "")[:50],
                        "size": int(item.get("size") or 0),
                        "sha": str(item.get("sha") or "")[:100],
                        "html_url": str(item.get("html_url") or "")[:2_048],
                    }
                    for item in data[:entry_limit]
                    if isinstance(item, dict)
                ],
                "truncated": len(data) > entry_limit,
            }
        if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
            raise ResearchError("GitHub path is not a supported file or directory")
        try:
            encoded = "".join(str(data.get("content") or "").split())
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ResearchError("GitHub returned invalid file content") from None
        if len(raw) > self.max_response_bytes:
            raise ResearchError("GitHub file exceeds the configured byte limit")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ResearchError("only UTF-8 GitHub text files can be read") from None
        content, truncated = self._bounded_text(decoded.replace("\x00", ""), max_chars)
        return {
            "operation": operation,
            "path": str(data.get("path") or clean_path),
            "html_url": str(data.get("html_url") or ""),
            "sha": str(data.get("sha") or ""),
            "size": len(raw),
            "content": content,
            "truncated": truncated,
        }
