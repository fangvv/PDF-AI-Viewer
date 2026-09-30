"""LaTeX → Unicode 兜底转换。

QTextEdit / QTextDocument 的 Markdown 渲染不支持 LaTeX 公式，模型偶尔仍会输出
$...$、\\frac 之类的语法。这里做一次兜底转换，把常见公式变成可读的 Unicode 纯文本。

供 main.py 的 SummaryWindow 与 chat_window.py 的 ChatWindow 共用。
"""

import re


def latex_to_unicode(text: str) -> str:
    """把常见的 LaTeX 数学公式转成可读的 Unicode 纯文本（兜底处理）。

    主要处理行内/块级公式定界符与常用命令，避免显示成原始 LaTeX 代码。
    """
    # 去掉公式定界符：$$...$$、$...$、\(...\)、\[...\]
    text = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.S)
    text = re.sub(r"\$(.+?)\$", r"\1", text, flags=re.S)
    text = re.sub(r"\\\[(.+?)\\\]", r"\1", text, flags=re.S)
    text = re.sub(r"\\\((.+?)\\\)", r"\1", text, flags=re.S)
    # 常用 LaTeX 命令 → Unicode
    replacements = {
        r"\times": "×", r"\cdot": "·", r"\pm": "±", r"\mp": "∓",
        r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
        r"\infty": "∞", r"\alpha": "α", r"\beta": "β", r"\gamma": "γ",
        r"\delta": "δ", r"\epsilon": "ε", r"\theta": "θ",
        r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω",
        r"\pi": "π", r"\sum": "∑", r"\prod": "∏", r"\int": "∫",
        r"\sqrt": "√", r"\partial": "∂", r"\nabla": "∇",
        r"\rightarrow": "→", r"\leftarrow": "←", r"\in": "∈",
        r"\notin": "∉", r"\subset": "⊂", r"\subseteq": "⊆",
        r"\cup": "∪", r"\cap": "∩", r"\forall": "∀", r"\exists": "∃",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # 上标：^{...} → Unicode 上标（仅数字/常见字母）
    sup_map = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
               "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
               "+": "⁺", "-": "⁻", "n": "ⁿ", "i": "ⁱ"}

    def _sup(m):
        inner = m.group(1)
        return "".join(sup_map.get(c, c) for c in inner)

    text = re.sub(r"\^\{([^{}]+)\}", _sup, text)
    text = re.sub(r"\^([0-9+\-ni])", lambda m: sup_map.get(m.group(1), m.group(1)), text)
    # 下标：_{...} → Unicode 下标（仅数字）
    sub_map = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
               "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
               "+": "₊", "-": "₋", "i": "ᵢ", "n": "ₙ"}

    def _sub(m):
        inner = m.group(1)
        return "".join(sub_map.get(c, c) for c in inner)

    text = re.sub(r"_\{([^{}]+)\}", _sub, text)
    text = re.sub(r"_([0-9+\-in])", lambda m: sub_map.get(m.group(1), m.group(1)), text)
    # 分数：\frac{a}{b} → (a)/(b)
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
    # 清理残留的反斜杠命令（保留未知命令原样，避免误删）
    return text
