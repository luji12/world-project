"""
Session-level API config registry.
The scheduler sets these at the start of each round so that
apply_* functions and memory_manager can call LLM for compression
without needing the credentials passed through every call chain.
"""

_config = {
    "api_key": "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
}


def set_session(api_key: str, base_url: str, model: str):
    _config["api_key"] = api_key
    _config["base_url"] = base_url
    _config["model"] = model


def get_api_key() -> str:
    return _config["api_key"]


def get_base_url() -> str:
    return _config["base_url"]


def get_model() -> str:
    return _config["model"]


def get_all() -> tuple:
    return _config["api_key"], _config["base_url"], _config["model"]
