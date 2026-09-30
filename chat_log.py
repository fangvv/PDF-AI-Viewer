"""阅读问答记录（Markdown）的读写。

问答内容写到与 PDF **同目录同名**的 .md 文件（A.pdf → A.md）：
既是人能直接阅读编辑的学习笔记，也是软件重新打开后接着聊的历史来源。

文件格式（每条问答以带序号的标题开头，便于逐条解析回来）::

    # A.pdf 阅读问答记录

    <!-- 说明行，不算正文 -->

    ## 1. 问：为什么要用 Transformer？
    > 第 3 页 · 2026-09-30 14:22

    **答：**

    因为……

    ---
"""

import datetime
import os
import re

import settings

# 文件头说明：首次创建时写入，提醒人这个文件是什么
HEADER_NOTE = (
    "<!-- 本文件由「PDF 阅读翻译器」的 AI 问答功能自动追加，"
    "可直接编辑、补充笔记；删除条目不影响阅读。 -->"
)

_ANSWER_MARK = "**答：**"

# 问题标题行：^## <序号>. 问：<问题>
_Q_RE = re.compile(r"^##[ \t]+\d+\.[ \t]*问：(.*)$", re.M)
# 上下文标记行：> 第 N 页 · 时间
_META_RE = re.compile(r"^>[ \t]*第[ \t]*(\d+)[ \t]*页[ \t]*·[ \t]*(.+?)[ \t]*$", re.M)


def md_path_for(pdf_path: str) -> str:
    """A.pdf → 同目录下的 A.md。"""
    return os.path.splitext(pdf_path)[0] + ".md"


def _header(pdf_path: str) -> str:
    return (
        f"# {os.path.basename(pdf_path)} 阅读问答记录\n\n"
        f"{HEADER_NOTE}\n\n"
    )


def _entry_count(text: str) -> int:
    """已有问答条数（按问题标题行统计，对无法逐条解析的文件同样适用）。"""
    return len(_Q_RE.findall(text))


def load_chat_log(pdf_path: str):
    """读取问答记录。

    返回 (exchanges, raw)：
    - 解析成功：exchanges 为问答列表，raw 为 None；
    - 文件不存在或为空：([], None)；
    - 文件格式被改坏 / 不是本功能写的：([], 原文)，界面按原文展示。
    """
    path = md_path_for(pdf_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return [], None
    if not text.strip():
        return [], None

    marks = list(_Q_RE.finditer(text))
    if not marks:
        return [], text

    exchanges = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.end():end]
        question = " ".join(m.group(1).split())
        page, when = 0, ""
        mm = _META_RE.search(block)
        if mm:
            page = int(mm.group(1))
            when = mm.group(2).strip()
        idx = block.find(_ANSWER_MARK)
        answer = block[idx + len(_ANSWER_MARK):] if idx >= 0 else block
        answer = answer.replace(HEADER_NOTE, "")
        answer = re.sub(r"\n?---\s*\Z", "", answer.strip()).strip()
        if question:
            exchanges.append({"q": question, "a": answer, "page": page, "time": when})
    return exchanges, None


def append_exchange(pdf_path: str, question: str, answer: str, page: int = 0):
    """追加一轮问答。

    返回 (实际写入路径, 错误信息)。PDF 所在目录不可写时，退回到用户目录下的
    chatnotes 备份文件，保证问答不会丢失（此时错误信息非空，界面需提示）。
    """
    question = " ".join((question or "").split())
    if not question:
        return None, "问题为空，未写入笔记"
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"## {_next_index(pdf_path)}. 问：{question}\n"]
    if page:
        lines.append(f"> 第 {page} 页 · {when}\n")
    else:
        lines.append(f"> {when}\n")
    lines.append(f"\n{_ANSWER_MARK}\n\n{(answer or '').strip()}\n\n---\n\n")
    entry = "".join(lines)

    path = md_path_for(pdf_path)
    try:
        _write_entry(path, pdf_path, entry)
        return path, None
    except OSError as exc:
        # PDF 所在目录只读/被占用 → 退回用户目录，内容不丢
        fallback = os.path.join(settings.chatnotes_dir(), os.path.basename(path))
        try:
            _write_entry(fallback, pdf_path, entry)
        except OSError as exc2:
            return None, f"写入问答笔记失败：{exc2}"
        return fallback, f"PDF 同目录不可写（{exc}），本次问答已改存到：{fallback}"


def _write_entry(path: str, pdf_path: str, entry: str) -> None:
    """追加写入；文件不存在时先写文件头。"""
    existed = os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if not existed:
            f.write(_header(pdf_path))
        f.write(entry)


def _next_index(pdf_path: str) -> int:
    """下一条问答的序号，尽量与文件里已有条数衔接。"""
    path = md_path_for(pdf_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = f.read()
    except OSError:
        return 1
    return _entry_count(head) + 1
