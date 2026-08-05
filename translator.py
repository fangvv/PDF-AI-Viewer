"""免费在线翻译引擎。

主引擎：微软 Edge 官方翻译 API（无需认证、国内可访问、翻译质量好、支持批量）
备用引擎：通用 OpenAI 兼容大模型（需 API Key，翻译质量高）、MyMemory（免费、无需 key）

失败时自动回退到下一个引擎。
"""

import requests


class TranslationError(Exception):
    """翻译失败异常。"""


class BaseTranslator:
    """翻译器基类。"""

    name = "base"

    def translate(self, text: str, src: str = "auto", dst: str = "zh") -> str:
        raise NotImplementedError


class EdgeTranslator(BaseTranslator):
    """微软 Edge 官方翻译 API（无需认证）。"""

    name = "微软 Edge 翻译"

    # 语言代码映射
    _LANG = {
        "zh": "zh-CHS",
        "en": "en",
        "ja": "ja",
        "ko": "ko",
        "fr": "fr",
        "de": "de",
        "es": "es",
        "ru": "ru",
    }

    def translate(self, text: str, src: str = "auto", dst: str = "zh") -> str:
        if not text.strip():
            return ""
        to = self._LANG.get(dst, dst)
        from_lang = "en" if src == "auto" else self._LANG.get(src, src)
        url = "https://edge.microsoft.com/translate/translatetext"
        params = {
            "from": from_lang,
            "to": to,
            "api-version": "3.0",
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
            "Origin": "https://www.microsoft.com",
            "Referer": "https://www.microsoft.com/",
        }
        resp = requests.post(url, params=params, json=[text], headers=headers, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if isinstance(result, list) and result:
            translations = result[0].get("translations", [])
            if translations:
                return translations[0].get("text", "")
        raise TranslationError("Edge 翻译返回异常: " + str(result)[:200])


class OpenAICompatTranslator(BaseTranslator):
    """通用 OpenAI 兼容大模型接口（需 API Key）。

    支持任意 OpenAI 兼容服务商（OpenRouter、DeepSeek、智谱、本地 Ollama 等），
    由用户配置 base_url、model、api_key。支持翻译、总结等大模型能力。
    """

    name = "大模型"

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _chat(self, prompt: str, timeout: int = 60) -> str:
        """调用大模型，返回文本结果。"""
        if not self.api_key:
            raise TranslationError("未配置大模型 API Key，请在「设置」中填写")
        if not self.base_url:
            raise TranslationError("未配置大模型接口地址，请在「设置」中填写")
        if not self.model:
            raise TranslationError("未配置大模型名称，请在「设置」中填写")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        # 强制 UTF-8 解码，避免服务商未声明 charset 时按 ISO-8859-1 解码导致乱码
        resp.encoding = "utf-8"
        result = resp.json()
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise TranslationError("大模型返回异常: " + str(result)[:200])
        if content and content.strip():
            return content.strip()
        raise TranslationError("大模型返回空结果")

    def _chat_stream(self, prompt: str, timeout: int = 120):
        """流式调用大模型，逐块 yield 文本内容。"""
        if not self.api_key:
            raise TranslationError("未配置大模型 API Key，请在「设置」中填写")
        if not self.base_url:
            raise TranslationError("未配置大模型接口地址，请在「设置」中填写")
        if not self.model:
            raise TranslationError("未配置大模型名称，请在「设置」中填写")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "stream": True,
        }
        with requests.post(url, json=payload, headers=headers, timeout=timeout,
                           stream=True) as resp:
            resp.raise_for_status()
            # 强制 UTF-8 解码，避免 SSE 流未声明 charset 时按 ISO-8859-1 解码导致乱码
            resp.encoding = "utf-8"
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                elif line == "data: [DONE]":
                    break
                else:
                    continue
                if data == "[DONE]":
                    break
                import json
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"].get("content", "")
                except (KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    def summarize_stream(self, text: str, lang: str = "zh"):
        """流式总结文本，逐块 yield 内容。"""
        if not text.strip():
            return
        prompt = (
            "你是一位精通各领域前沿研究的学术文献解读专家，面对一篇给定的论文，"
            "请你高效阅读并迅速提取出其核心内容。要求在解读过程中，"
            "先对文献的背景、研究目的和问题进行简明概述，再详细梳理研究方法、"
            "关键数据、主要发现及结论，同时对新颖概念进行通俗易懂的解释，"
            "帮助读者理解论文的逻辑与创新点；最后，请对文献的优缺点进行客观评价，"
            "并指出可能的后续研究方向。整体报告结构清晰、逻辑严谨。\n"
            "请务必使用中文输出，并可使用 Markdown 格式（如标题、列表、加粗）"
            "使报告层次分明、便于阅读。\n"
            "重要：遇到数学公式时，请使用 Unicode 数学符号和纯文本表示"
            "（例如 E = mc²、x₁ + x₂、f(x) = ax² + bx + c），"
            "不要使用 LaTeX 语法（如 $...$、\\frac、^、_ 等），"
            "因为本软件无法渲染 LaTeX 公式。\n\n"
            "以下是待解读的论文文本：\n\n"
            f"{text}"
        )
        yield from self._chat_stream(prompt)

    def list_models(self) -> list:
        """从服务商拉取可用模型列表。"""
        if not self.base_url:
            raise TranslationError("未配置大模型接口地址，请在「设置」中填写")
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        models = result.get("data", [])
        names = []
        for m in models:
            mid = m.get("id")
            if mid:
                names.append(mid)
        return names

    def translate(self, text: str, src: str = "auto", dst: str = "zh") -> str:
        if not text.strip():
            return ""
        prompt = (
            f"请将以下文本翻译成{'中文' if dst == 'zh' else dst}，"
            f"只输出翻译结果，不要添加任何解释或原文：\n\n{text}"
        )
        return self._chat(prompt)

    def summarize(self, text: str, lang: str = "zh") -> str:
        """总结文本内容。"""
        if not text.strip():
            return ""
        prompt = (
            "你是一位精通各领域前沿研究的学术文献解读专家，面对一篇给定的论文，"
            "请你高效阅读并迅速提取出其核心内容。要求在解读过程中，"
            "先对文献的背景、研究目的和问题进行简明概述，再详细梳理研究方法、"
            "关键数据、主要发现及结论，同时对新颖概念进行通俗易懂的解释，"
            "帮助读者理解论文的逻辑与创新点；最后，请对文献的优缺点进行客观评价，"
            "并指出可能的后续研究方向。整体报告结构清晰、逻辑严谨。\n"
            "请务必使用中文输出，并可使用 Markdown 格式（如标题、列表、加粗）"
            "使报告层次分明、便于阅读。\n"
            "重要：遇到数学公式时，请使用 Unicode 数学符号和纯文本表示"
            "（例如 E = mc²、x₁ + x₂、f(x) = ax² + bx + c），"
            "不要使用 LaTeX 语法（如 $...$、\\frac、^、_ 等），"
            "因为本软件无法渲染 LaTeX 公式。\n\n"
            "以下是待解读的论文文本：\n\n"
            f"{text}"
        )
        return self._chat(prompt, timeout=90)


class MyMemoryTranslator(BaseTranslator):
    """MyMemory 免费翻译 API（无需 key）。"""

    name = "MyMemory"

    def translate(self, text: str, src: str = "auto", dst: str = "zh") -> str:
        if not text.strip():
            return ""
        lang = "zh-CN" if dst == "zh" else dst
        src_code = "en" if src == "auto" else src
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text,
            "langpair": f"{src_code}|{lang}",
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("responseStatus") == 200:
            translated = result.get("responseData", {}).get("translatedText", "")
            if translated:
                return translated
        raise TranslationError("MyMemory 返回异常: " + str(result)[:200])


class Translator:
    """翻译管理器，支持自动回退或指定引擎。"""

    def __init__(self, llm_key: str = "", llm_base_url: str = "", llm_model: str = ""):
        self.llm = OpenAICompatTranslator(llm_key, llm_base_url, llm_model)
        self.engines = [
            EdgeTranslator(),
            self.llm,
            MyMemoryTranslator(),
        ]

    def configure_llm(self, api_key: str, base_url: str, model: str):
        """配置大模型参数。"""
        self.llm.api_key = api_key
        self.llm.base_url = base_url.rstrip("/")
        self.llm.model = model

    def list_llm_models(self) -> list:
        """拉取大模型可用模型列表。"""
        return self.llm.list_models()

    def summarize(self, text: str, lang: str = "zh") -> str:
        """用大模型总结文本。"""
        return self.llm.summarize(text, lang=lang)

    def summarize_stream(self, text: str, lang: str = "zh"):
        """流式总结文本，逐块 yield 内容。"""
        yield from self.llm.summarize_stream(text, lang=lang)

    def engine_names(self) -> list:
        """返回所有引擎名称。"""
        return [e.name for e in self.engines]

    def translate(self, text: str, src: str = "auto", dst: str = "zh",
                  engine: str = "auto") -> str:
        """翻译文本。

        engine: "auto" 表示自动回退；否则指定引擎名称。
        """
        if not text.strip():
            return ""
        if engine != "auto":
            # 指定引擎
            for e in self.engines:
                if e.name == engine:
                    return e.translate(text, src=src, dst=dst)
            raise TranslationError(f"未知翻译引擎: {engine}")
        # 自动回退
        errors = []
        for e in self.engines:
            try:
                result = e.translate(text, src=src, dst=dst)
                if result and result.strip():
                    return result
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{e.name}: {exc}")
        raise TranslationError("所有翻译引擎均失败: " + "; ".join(errors))
