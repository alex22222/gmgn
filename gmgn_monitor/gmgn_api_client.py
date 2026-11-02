from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from pathlib import Path
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


__all__ = [
    "GmgnApiError",
    "GmgnApiClient",
    "GmgnSigner",
    "USER_AGENT",
    "build_message",
]


DEFAULT_TIMEOUT = 30  # seconds
USER_AGENT = "gmgn-cli/1.0.0"

# Fallback OpenSSL 3.x paths (macOS Homebrew)
_OPENSSL_PATHS = [
    "/opt/homebrew/opt/openssl/bin/openssl",
    "/opt/homebrew/opt/openssl@3.6/bin/openssl",
    "/opt/homebrew/opt/openssl@3/bin/openssl",
    "/usr/local/opt/openssl/bin/openssl",
    "/usr/local/opt/openssl@3/bin/openssl",
]


class GmgnApiError(Exception):
    """Raised when the GMGN API returns a non-success response.

    Attributes:
        code: GMGN API error code (``None`` if not available).
        http_status: HTTP status code (``None`` if not an HTTP error).
    """

    def __init__(
        self,
        message: str,
        code: int | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    @property
    def message(self) -> str:
        """Return the error message string."""
        return self.args[0] if self.args else ""


class GmgnSigner:
    """Ed25519 / RSA signer that mirrors gmgn-cli's ``signer.js``.

    Supports three backends (tried in order):

    1. **cryptography** (preferred) — ``pip install cryptography``
    2. **pynacl** — ``pip install pynacl``
    3. **Homebrew OpenSSL 3.x** (macOS fallback) — no extra deps

    Usage::

        signer = GmgnSigner.from_pem("~/.config/gmgn/keypair.pem")
        sig = signer.sign("hello world")
    """

    def __init__(self, private_key_pem: str, algorithm: str = "Ed25519") -> None:
        self._pem = private_key_pem
        self._algorithm = algorithm

    @classmethod
    def from_pem(cls, pem_path: str) -> "GmgnSigner":
        """Load a signer from a PEM file path."""
        with open(os.path.expanduser(pem_path), "r", encoding="utf-8") as f:
            pem = f.read()
        return cls(private_key_pem=pem, algorithm=cls._detect_algorithm(pem))

    @classmethod
    def from_pem_content(cls, pem_content: str) -> "GmgnSigner":
        """Load a signer from raw PEM string content."""
        return cls(private_key_pem=pem_content, algorithm=cls._detect_algorithm(pem_content))

    @staticmethod
    def _detect_algorithm(pem: str) -> str:
        """Detect signing algorithm from PEM key.

        Matches gmgn-cli's ``detectAlgorithm``:
        Ed25519 → ``"Ed25519"``, RSA → ``"RSA-SHA256"``.
        """
        # Simple heuristic: Ed25519 keys contain the word "Ed25519" in the PEM
        # or have a specific key length. A more robust check would be to parse ASN.1,
        # but for our use case the PEM header is sufficient.
        lower = pem.lower()
        if "ed25519" in lower or "private key" in lower and "mc4c" in lower:
            return "Ed25519"
        if "rsa" in lower:
            return "RSA-SHA256"
        # Fallback: try to sign a dummy message to detect
        return "Ed25519"

    def sign(self, message: str) -> str:
        """Sign a message and return the base64-encoded signature.

        For Ed25519: signs raw message bytes (no pre-hashing).
        For RSA: RSA-PSS + SHA256 with salt length 32.
        """
        msg_bytes = message.encode("utf-8")

        # 1. Try cryptography
        try:
            return self._sign_with_cryptography(msg_bytes)
        except ImportError:
            pass

        # 2. Try pynacl
        try:
            return self._sign_with_pynacl(msg_bytes)
        except ImportError:
            pass

        # 3. Fallback to OpenSSL 3.x
        return self._sign_with_openssl(msg_bytes)

    def _sign_with_cryptography(self, msg_bytes: bytes) -> str:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = serialization.load_pem_private_key(self._pem.encode(), password=None)
        if self._algorithm == "Ed25519":
            sig = key.sign(msg_bytes)  # type: ignore[union-attr]
        else:
            # RSA-PSS + SHA256
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            sig = key.sign(  # type: ignore[union-attr]
                msg_bytes,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                hashes.SHA256(),
            )
        return base64.b64encode(sig).decode()

    def _sign_with_pynacl(self, msg_bytes: bytes) -> str:
        from nacl.signing import SigningKey
        from nacl.encoding import Base64Encoder

        # Extract the 32-byte seed from the PEM
        # For Ed25519 PKCS#8 PEM, the private key is 48 bytes total (header + 32-byte seed)
        pem_lines = self._pem.strip().splitlines()
        b64 = "".join(line for line in pem_lines if not line.startswith("-----"))
        der = base64.b64decode(b64)
        # Ed25519 PKCS#8: SEQUENCE { INTEGER 0, SEQUENCE { OID 1.3.101.112 }, OCTET STRING { OCTET STRING { 32-byte seed } } }
        # The last 32 bytes of the outer OCTET STRING are the seed
        seed = der[-32:]
        signing_key = SigningKey(seed)
        signed = signing_key.sign(msg_bytes)
        return base64.b64encode(signed.signature).decode()

    def _sign_with_openssl(self, msg_bytes: bytes) -> str:
        openssl_path = self._find_openssl()
        if not openssl_path:
            raise RuntimeError(
                "No Ed25519 signing backend available. "
                "Install 'cryptography' (pip install cryptography) or "
                "'pynacl' (pip install pynacl), or ensure OpenSSL 3.x is on PATH."
            )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
            kf.write(self._pem)
            key_path = kf.name
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as mf:
            mf.write(msg_bytes)
            msg_path = mf.name
        with tempfile.NamedTemporaryFile(suffix=".sig", delete=False) as sf:
            sig_path = sf.name

        try:
            cmd = [
                openssl_path,
                "pkeyutl",
                "-sign",
                "-in", msg_path,
                "-inkey", key_path,
                "-out", sig_path,
            ]
            if self._algorithm == "Ed25519":
                cmd.append("-rawin")
            subprocess.run(cmd, check=True, capture_output=True)
            with open(sig_path, "rb") as f:
                sig = f.read()
            return base64.b64encode(sig).decode()
        finally:
            for p in (key_path, msg_path, sig_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    @staticmethod
    def _find_openssl() -> str | None:
        for p in _OPENSSL_PATHS:
            if os.path.exists(p):
                return p
        # Also try PATH
        for p in ("openssl",):
            try:
                subprocess.run([p, "version"], check=True, capture_output=True)
                return p
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        return None


def build_message(sub_path: str, query_params: dict[str, Any], body: str | None, timestamp: int) -> str:
    """Build the signature message (matching gmgn-cli's ``buildMessage``).

    Format::

        {sub_path}:{sorted_query_string}:{request_body}:{timestamp}

    ``sorted_query_string`` uses ``encodeURIComponent`` (``urllib.parse.quote``)
    on both keys and values.  Array values are sorted and emitted as repeated
    ``k=v`` pairs.
    """
    parts: list[str] = []
    for k in sorted(query_params.keys()):
        ek = urllib.parse.quote(str(k), safe="")
        v = query_params[k]
        if isinstance(v, list):
            for item in sorted(v):
                parts.append(f"{ek}={urllib.parse.quote(str(item), safe='')}")
        else:
            parts.append(f"{ek}={urllib.parse.quote(str(v), safe='')}")
    sorted_qs = "&".join(parts)
    return f"{sub_path}:{sorted_qs}:{body or ''}:{timestamp}"


def _is_stale_timestamp(message: str) -> bool:
    """GMGN rejects an auth query once its ``timestamp`` is too old."""
    return "timestamp expired" in message.lower()


def _http_error_message(error: urllib.error.HTTPError) -> tuple[str, int | None]:
    try:
        error_body = error.read().decode("utf-8")
        error_parsed = json.loads(error_body)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return f"HTTP {error.code}: {error.reason}", None
    return str(error_parsed.get("message", f"HTTP {error.code}")), error_parsed.get("code")


def _clean_body_for_json(obj: Any) -> Any:
    """Recursively convert float values that are whole numbers to int.

    JavaScript's JSON.stringify(2.0) produces "2" (not "2.0").
    Python's json.dumps(2.0) produces "2.0". This causes signature mismatch
    because the body string is part of the signed message.
    """
    if isinstance(obj, dict):
        return {k: _clean_body_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_body_for_json(item) for item in obj]
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


def _tls_context() -> ssl.SSLContext | None:
    default_cafile = ssl.get_default_verify_paths().cafile
    if default_cafile and Path(default_cafile).exists():
        return None
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


class GmgnApiClient:
    """Python HTTP client for the GMGN OpenAPI.

    Supports both authentication modes (matching gmgn-cli):

    * **Exist auth** (read-only endpoints): ``X-APIKEY`` + ``timestamp`` + ``client_id``.
    * **Signed auth** (swap/order endpoints): ``X-APIKEY`` + ``timestamp`` +
      ``client_id`` + ``X-Signature`` (Ed25519 / RSA private key signature).

    Cloudflare's browser-signature check requires the ``User-Agent`` header to
    match ``gmgn-cli/…`` — this is handled automatically.
    """

    def __init__(
        self,
        api_key: str,
        private_key_pem: str | None = None,
        host: str = "https://openapi.gmgn.ai",
    ) -> None:
        self._api_key = api_key
        self._host = host.rstrip("/")
        self._signer = None
        if private_key_pem:
            self._signer = GmgnSigner.from_pem_content(private_key_pem)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_auth_query(self) -> dict[str, Any]:
        """Return timestamp + client_id query params (matching ``buildAuthQuery``)."""
        return {
            "timestamp": int(time.time()),
            "client_id": str(uuid.uuid4()),
        }

    def _build_url(self, path: str, query: dict[str, Any]) -> str:
        """Build URL with query parameters (matching gmgn-cli's ``buildUrl``)."""
        if not path.startswith("/"):
            path = "/" + path
        parts: list[str] = []
        for k, v in sorted(query.items()):
            if isinstance(v, list):
                for item in v:
                    parts.append(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(item))}")
            else:
                parts.append(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(v))}")
        qs = "&".join(parts)
        return f"{self._host}{path}?{qs}"

    def _auth_exist_request(
        self,
        method: str,
        sub_path: str,
        query_extra: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an *exist*-auth request (no signature required)."""
        def prepare() -> tuple[str, str, dict[str, str], str | None]:
            query: dict[str, Any] = {**(query_extra or {}), **self._build_auth_query()}
            headers = {
                "X-APIKEY": self._api_key,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            }
            body_str = json.dumps(body) if body else None
            return method, self._build_url(sub_path, query), headers, body_str

        return self._execute(prepare)

    def _auth_signed_request(
        self,
        method: str,
        sub_path: str,
        query_extra: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a *signed*-auth request (requires private key)."""
        if self._signer is None:
            raise GmgnApiError(
                "GMGN_PRIVATE_KEY is required for signed-auth endpoints."
            )

        def prepare() -> tuple[str, str, dict[str, str], str | None]:
            auth = self._build_auth_query()
            query: dict[str, Any] = {**(query_extra or {}), **auth}
            # Match JavaScript JSON.stringify: 2.0 -> "2", not "2.0"
            body_cleaned = _clean_body_for_json(body) if body else None
            body_str = json.dumps(body_cleaned, separators=(',', ':')) if body_cleaned else ""
            message = build_message(sub_path, query, body_str, auth["timestamp"])
            headers = {
                "X-APIKEY": self._api_key,
                "X-Signature": self._signer.sign(message),
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            }
            return method, self._build_url(sub_path, query), headers, body_str or None

        return self._execute(prepare)

    def _execute(
        self,
        prepare: Callable[[], tuple[str, str, dict[str, str], str | None]],
    ) -> dict[str, Any]:
        """Execute a prepared HTTP request with retry logic.

        Each attempt calls *prepare* again. GMGN rejects a stale ``timestamp``,
        and a signed request also has to be signed over that new timestamp.
        """
        max_retries = 1

        for attempt in range(max_retries + 1):
            method, url, headers, body_str = prepare()
            data = body_str.encode("utf-8") if body_str else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                kwargs: dict[str, Any] = {"timeout": DEFAULT_TIMEOUT}
                context = _tls_context()
                if context is not None:
                    kwargs["context"] = context
                response = urllib.request.urlopen(req, **kwargs)
                try:
                    body_text = response.read().decode("utf-8")
                    parsed = json.loads(body_text)
                finally:
                    response.close()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries:
                    self._sleep_for_rate_limit(e)
                    continue
                message, code = _http_error_message(e)
                if attempt < max_retries and _is_stale_timestamp(message):
                    time.sleep(0.2)
                    continue
                raise GmgnApiError(message, code=code, http_status=e.code) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < max_retries:
                    time.sleep(1.0)
                    continue
                raise GmgnApiError(
                    f"Network error: {e}", code=None, http_status=None
                ) from e
            except json.JSONDecodeError as e:
                raise GmgnApiError(
                    f"Invalid JSON: {e}", code=None, http_status=None
                ) from e

            if parsed.get("code", 0) != 0:
                message = str(parsed.get("message", "Unknown API error"))
                if attempt < max_retries and _is_stale_timestamp(message):
                    time.sleep(0.2)
                    continue
                raise GmgnApiError(
                    message,
                    code=parsed.get("code"),
                    http_status=None,
                )
            return parsed.get("data", {})

        raise GmgnApiError("Rate limit retry exceeded")

    @staticmethod
    def _sleep_for_rate_limit(error: urllib.error.HTTPError) -> None:
        reset_ts = error.headers.get("x-ratelimit-reset")
        if reset_ts:
            wait_until = float(reset_ts) + 1.0
            sleep_time = min(30.0, max(0.1, wait_until - time.time()))
            time.sleep(sleep_time)
            return
        time.sleep(1.0)

    # ------------------------------------------------------------------
    # Public API — Exist auth (read-only)
    # ------------------------------------------------------------------

    def get_wallet_stats(
        self,
        chain: str,
        wallet_addresses: list[str],
        period: str = "7d",
    ) -> dict[str, Any]:
        """Fetch wallet trading statistics.

        Calls ``GET /v1/user/wallet_stats`` (exist auth).
        """
        # Note: gmgn-cli uses "wallet_address" (singular) even for a list of addresses
        # The API expects a comma-separated string of addresses
        return self._auth_exist_request(
            "GET",
            "/v1/user/wallet_stats",
            {"chain": chain, "wallet_address": ",".join(wallet_addresses), "period": period},
        )

    def get_wallet_activity(
        self,
        chain: str,
        wallet_address: str,
        limit: int = 50,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch recent activity for a single wallet.

        Calls ``GET /v1/user/wallet_activity`` (exist auth).
        """
        query: dict[str, Any] = {"chain": chain, "wallet_address": wallet_address, "limit": limit}
        query.update(extra)
        return self._auth_exist_request("GET", "/v1/user/wallet_activity", query)

    def get_smartmoney(
        self,
        chain: str = "sol",
        limit: int = 100,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch the Smart Money wallet list.

        Calls ``GET /v1/user/smartmoney`` (exist auth).
        """
        query: dict[str, Any] = {}
        if chain:
            query["chain"] = chain
        if limit is not None:
            query["limit"] = limit
        query.update(extra)
        return self._auth_exist_request("GET", "/v1/user/smartmoney", query)

    def get_kol(
        self,
        chain: str = "sol",
        limit: int = 100,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch KOL trade records.

        Calls ``GET /v1/user/kol`` (exist auth).
        """
        query: dict[str, Any] = {}
        if chain:
            query["chain"] = chain
        if limit is not None:
            query["limit"] = limit
        query.update(extra)
        return self._auth_exist_request("GET", "/v1/user/kol", query)

    def get_token_top_traders(
        self,
        chain: str,
        token_address: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch top traders for a specific token.

        Calls ``GET /v1/market/token_top_traders`` (exist auth).
        """
        query: dict[str, Any] = {"chain": chain, "address": token_address, "token_address": token_address}
        query.update(extra)
        return self._auth_exist_request("GET", "/v1/market/token_top_traders", query)

    def get_trending_swaps(
        self,
        chain: str,
        interval: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch trending swap rankings.

        Calls ``GET /v1/market/rank`` (exist auth).
        """
        query: dict[str, Any] = {"chain": chain, "interval": interval}
        query.update(extra)
        return self._auth_exist_request("GET", "/v1/market/rank", query)

    def get_token_signals(
        self,
        chain: str,
        groups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Fetch token signal events.

        Calls ``POST /v1/market/token_signal`` (exist auth).
        """
        return self._auth_exist_request(
            "POST",
            "/v1/market/token_signal",
            {},
            {"chain": chain, "groups": groups},
        )

    # ------------------------------------------------------------------
    # Public API — Signed auth (requires private key)
    # ------------------------------------------------------------------

    def get_wallet_holdings(
        self,
        chain: str,
        wallet_address: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Fetch wallet holdings.

        Calls ``GET /v1/user/wallet_holdings`` (signed auth).
        """
        query: dict[str, Any] = {"chain": chain, "wallet_address": wallet_address, **extra}
        return self._auth_signed_request("GET", "/v1/user/wallet_holdings", query, None)

    def swap(self, params: dict[str, Any]) -> dict[str, Any]:
        """Submit a swap order.

        Calls ``POST /v1/trade/swap`` (signed auth).
        """
        return self._auth_signed_request("POST", "/v1/trade/swap", {}, params)

    def get_gas_price(self, chain: str) -> dict[str, Any]:
        """Fetch gas price.

        Calls ``GET /v1/trade/gas_price`` (exist auth).
        """
        return self._auth_exist_request("GET", "/v1/trade/gas_price", {"chain": chain})
