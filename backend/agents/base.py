import json
import os
import sys
import ssl
import http.client
import urllib.request
import urllib.error


class AgentError(Exception):
    pass


def _create_ssl_context():
    strategies = []

    try:
        import certifi
        strategies.append(("certifi", lambda: ssl.create_default_context(cafile=certifi.where())))
    except ImportError:
        pass

    sys_cert = "/etc/ssl/cert.pem"
    if os.path.exists(sys_cert):
        strategies.append(("system-cert", lambda: ssl.create_default_context(cafile=sys_cert)))

    strategies.append(("default", lambda: ssl.create_default_context()))

    last_error = None
    for name, factory in strategies:
        try:
            ctx = factory()
            sys.stderr.write(f"[ssl] using strategy: {name}\n")
            sys.stderr.flush()
            return ctx
        except Exception as e:
            last_error = e
            sys.stderr.write(f"[ssl] strategy '{name}' failed: {e}\n")
            sys.stderr.flush()

    raise last_error or Exception("Failed to create SSL context with any strategy")


def create_opener():
    ctx = _create_ssl_context()
    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=ctx))
    else:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    return opener


def _safe_json_parse(content, fallback_key="raw_output"):
    if not content or not content.strip():
        return {fallback_key: ""}
    content = content.strip()
    try:
        result = json.loads(content)
        return result if isinstance(result, dict) else {fallback_key: result}
    except json.JSONDecodeError:
        pass
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        try:
            result = json.loads(content[start:end+1])
            return result if isinstance(result, dict) else {fallback_key: result}
        except json.JSONDecodeError:
            pass
    return {fallback_key: content[:2000]}


def normalize_agent_output(value, fallback_key="raw_output") -> dict:
    """Return a dict-shaped agent output regardless of model drift.

    LLM providers occasionally return a top-level list/string even when JSON is
    requested.  Downstream agents are written around object-shaped contracts, so
    this is the single guardrail before callers inspect fields with `.get()`.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return _safe_json_parse(value, fallback_key=fallback_key)
    if isinstance(value, list):
        return {fallback_key: value}
    if value is None:
        return {fallback_key: ""}
    return {fallback_key: str(value)[:2000]}


def ensure_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def ensure_list(value) -> list:
    return value if isinstance(value, list) else []


def ensure_list_of_dicts(value) -> list:
    return [item for item in ensure_list(value) if isinstance(item, dict)]


def _extract_tokens_from_buffer(buffer):
    """Process SSE buffer, yield (token, done) tuples and return remaining buffer."""
    remaining = buffer
    tokens = []
    done = False
    while "\n" in remaining:
        line, remaining = remaining.split("\n", 1)
        line = line.strip()
        if not line:
            continue
        if line == "data: [DONE]":
            done = True
            break
        if line.startswith("data: "):
            data_str = line[len("data: "):]
            try:
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    tokens.append(content)
            except (json.JSONDecodeError, Exception):
                continue
    return tokens, remaining, done


def call_deepseek(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> dict:
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    sys.stderr.write(f"[agent] calling {url} model={model}\n")
    sys.stderr.flush()

    opener = create_opener()

    try:
        with opener.open(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            return _safe_json_parse(content)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8") if e.fp else ""
        raise AgentError(f"DeepSeek API error {e.code}: {body_text[:300]}")
    except urllib.error.URLError as e:
        raise AgentError(f"Network error: {e.reason}")
    except Exception as e:
        raise AgentError(f"Request failed: {e}")


def call_deepseek_stream(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_tokens: int = 4096,
    temperature: float = 0.7,
):
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "response_format": {"type": "json_object"},
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    sys.stderr.write(f"[agent] calling {url} model={model} (stream)\n")
    sys.stderr.flush()

    opener = create_opener()

    try:
        with opener.open(req, timeout=120) as resp:
            buffer = ""
            byte_buf = b""
            while True:
                try:
                    chunk = resp.read(4096)
                except http.client.IncompleteRead as inc:
                    partial = inc.partial or b""
                    candidate = byte_buf + partial
                    try:
                        buffer += candidate.decode("utf-8")
                    except Exception:
                        buffer += candidate.decode("utf-8", errors="replace")
                    byte_buf = b""
                    tokens, buffer, done = _extract_tokens_from_buffer(buffer)
                    for t in tokens:
                        yield t
                    sys.stderr.write(f"[stream] IncompleteRead, yielded {len(tokens)} partial tokens\n")
                    sys.stderr.flush()
                    return

                if not chunk:
                    if byte_buf:
                        buffer += byte_buf.decode("utf-8", errors="replace")
                        byte_buf = b""
                    break

                candidate = byte_buf + chunk
                try:
                    buffer += candidate.decode("utf-8")
                    byte_buf = b""
                except UnicodeDecodeError as ude:
                    if ude.reason == "unexpected end of data":
                        buffer += candidate[:ude.start].decode("utf-8")
                        byte_buf = candidate[ude.start:]
                    else:
                        buffer += candidate.decode("utf-8", errors="replace")
                        byte_buf = b""

                tokens, buffer, done = _extract_tokens_from_buffer(buffer)
                for t in tokens:
                    yield t
                if done:
                    return
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8") if e.fp else ""
        raise AgentError(f"DeepSeek API error {e.code}: {body_text[:300]}")
    except urllib.error.URLError as e:
        raise AgentError(f"Network error: {e.reason}")
    except Exception as e:
        sys.stderr.write(f"[stream] connection error, using partial data: {e}\n")
        sys.stderr.flush()
