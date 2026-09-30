"""配置与阅读位置记录。

阅读位置自动记录到用户目录下的 JSON 文件，按 PDF 文件路径索引。
"""

import json
import os
import sys

APP_NAME = "PDFTranslator"


def _config_dir() -> str:
    """返回配置目录（用户目录下）。"""
    base = os.path.expanduser("~")
    path = os.path.join(base, "." + APP_NAME.lower())
    os.makedirs(path, exist_ok=True)
    return path


def _positions_file() -> str:
    return os.path.join(_config_dir(), "reading_positions.json")


def _settings_file() -> str:
    return os.path.join(_config_dir(), "settings.json")


def chatnotes_dir() -> str:
    """问答笔记回退目录：当 PDF 所在目录不可写时，把 .md 写到这里。"""
    path = os.path.join(_config_dir(), "chatnotes")
    os.makedirs(path, exist_ok=True)
    return path


def _recent_file() -> str:
    return os.path.join(_config_dir(), "recent.json")


MAX_RECENT = 10


def load_recent() -> list:
    """加载最近打开的文件列表（最新的在前）。"""
    try:
        with open(_recent_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def add_recent(pdf_path: str) -> None:
    """把文件加入最近打开列表（去重，最新的在前）。"""
    recent = load_recent()
    if pdf_path in recent:
        recent.remove(pdf_path)
    recent.insert(0, pdf_path)
    recent = recent[:MAX_RECENT]
    try:
        with open(_recent_file(), "w", encoding="utf-8") as f:
            json.dump(recent, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def remove_recent(pdf_path: str) -> None:
    """从最近打开列表移除指定文件。"""
    recent = load_recent()
    if pdf_path in recent:
        recent.remove(pdf_path)
        try:
            with open(_recent_file(), "w", encoding="utf-8") as f:
                json.dump(recent, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def clear_recent() -> None:
    """清空最近打开列表。"""
    try:
        with open(_recent_file(), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_positions() -> dict:
    """加载所有 PDF 的阅读位置记录。"""
    try:
        with open(_positions_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_position(pdf_path: str, page: int, scroll: int = 0) -> None:
    """保存某个 PDF 的阅读位置。"""
    positions = load_positions()
    positions[pdf_path] = {"page": page, "scroll": scroll}
    try:
        with open(_positions_file(), "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_position(pdf_path: str) -> dict | None:
    """获取某个 PDF 的阅读位置，无则返回 None。"""
    return load_positions().get(pdf_path)


def load_settings() -> dict:
    """加载界面设置（如分栏宽度）。"""
    try:
        with open(_settings_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict) -> None:
    """保存界面设置。"""
    try:
        with open(_settings_file(), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_llm_key() -> str:
    """从系统凭据管理器获取大模型 API Key。"""
    try:
        import keyring
        return keyring.get_password(APP_NAME, "llm_key") or ""
    except Exception:  # noqa: BLE001
        return ""


def save_llm_key(api_key: str) -> None:
    """保存大模型 API Key 到系统凭据管理器。"""
    try:
        import keyring
        if api_key:
            keyring.set_password(APP_NAME, "llm_key", api_key)
        else:
            try:
                keyring.delete_password(APP_NAME, "llm_key")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def get_llm_base_url() -> str:
    """获取大模型接口地址。"""
    return load_settings().get("llm_base_url", "")


def get_llm_model() -> str:
    """获取大模型名称。"""
    return load_settings().get("llm_model", "")


def save_llm_config(base_url: str, model: str) -> None:
    """保存大模型接口地址和模型名。"""
    s = load_settings()
    s["llm_base_url"] = base_url
    s["llm_model"] = model
    save_settings(s)
