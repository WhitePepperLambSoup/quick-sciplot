"""LLM 封装：OpenAI 兼容 chat/completions + 提示词 + mock 模式。"""

import json
import re
import time

import httpx

from .config import settings

SYSTEM_PROMPT = """你是一名科研绘图助手。根据用户需求和数据摘要，输出一段可直接执行的 Python 代码。

硬性要求：
1. 只输出代码本身，不要 markdown 围栏、不要解释文字。
2. 数据已经加载到变量 `df`（pandas.DataFrame），直接使用，不要再读取文件。
3. 只允许导入白名单库：matplotlib、numpy、pandas、seaborn、scipy、statsmodels、plotly、math、statistics、random。
4. 静态图使用 matplotlib（Agg 后端已自动设置）；若用户明确要求交互图，使用 plotly.express 或 plotly.graph_objects，并把图对象赋值给变量 `fig`。不要调用 show、savefig、write_html（由系统自动保存）。
5. 中文文本标签请在代码内设置 matplotlib 中文字体（例如 plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']），并加 plt.rcParams['axes.unicode_minus'] = False。
6. 代码必须健壮：对缺失值做处理，避免运行时错误。
7. 一个完整绘图（可有多个子图），图要美观、适合期刊发表。
8. 系统会在执行代码前自动应用用户选择的风格预设，不要导入第三方预设包，也不要用 plt.style.use 覆盖系统预设。

数据摘要如下：
"""


class LLMError(Exception):
    pass


class LLMEmptyResponseError(LLMError):
    pass


def test_connection() -> dict:
    """发送最小请求，供设置页验证当前模型配置。"""
    started = time.perf_counter()
    content = _call_chat(
        [
            {"role": "system", "content": "You are a connectivity check. Reply with OK only."},
            {"role": "user", "content": "Reply with OK."},
        ],
        temperature=0,
    )
    return {
        "ok": True,
        "mode": "mock" if settings.llm_mock else "api",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "preview": content.strip()[:120],
    }


def _call_chat(messages: list[dict], temperature: float = 0.3) -> str:
    if settings.llm_mock:
        return _mock_reply(messages)

    if not settings.llm_api_key:
        raise LLMError("未配置 LLM_API_KEY（可在 backend/.env 中配置，或设置 LLM_MOCK=1 使用演示模式）")

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": settings.llm_max_tokens,
    }
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=180) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"LLM 接口返回 {exc.response.status_code}: {exc.response.text[:500]}") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM 接口请求失败: {exc}") from exc

    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            if "".join(parts).strip():
                return "".join(parts)
        completion = choice.get("text")
        if isinstance(completion, str) and completion.strip():
            return completion
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str):
            fenced = re.findall(r"```(?:python)?\s*(.*?)```", reasoning, flags=re.DOTALL | re.IGNORECASE)
            if fenced:
                return fenced[-1]
        finish_reason = choice.get("finish_reason", "unknown")
        keys = ", ".join(message.keys()) if isinstance(message, dict) else "unknown"
        raise LLMEmptyResponseError(
            f"模型返回空内容（model={settings.llm_model}, finish_reason={finish_reason}, message_keys={keys}）。"
            "请检查模型名称、token 上限和 API 配置。"
        )
    except LLMError:
        raise
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"LLM 响应格式异常: {str(data)[:500]}") from exc


def _extract_code(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _call_code(messages: list[dict]) -> str:
    try:
        return _call_chat(messages)
    except LLMEmptyResponseError:
        retry_messages = list(messages)
        retry_messages.append(
            {
                "role": "user",
                "content": "上一轮没有返回可执行内容。请重新回答，只输出完整 Python 代码，不要输出思考过程、解释或 markdown。",
            }
        )
        return _call_chat(retry_messages, temperature=0.1)


def generate_plot_code(instruction: str, summary: dict, preset: str | None = None) -> str:
    preset_hint = f"\n系统选择的风格预设 ID：{preset or 'default'}（执行器会自动应用，请不要在代码中重复设置全局风格）"
    user_msg = f"用户想画的图：{instruction}\n{json.dumps(summary, ensure_ascii=False, indent=1)[:6000]}{preset_hint}"
    code = _extract_code(_call_code([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]))
    if not code.strip():
        raise LLMError("LLM 返回了空代码")
    return code


def edit_plot_code(code: str, instruction: str, summary: dict, preset: str | None = None) -> str:
    user_msg = (
        "这是当前绘图代码：\n```python\n" + code + "\n```\n\n"
        f"请按下面的修改要求输出修改后的完整代码（保持其余部分不变）：\n{instruction}\n\n"
        f"数据摘要：\n{json.dumps(summary, ensure_ascii=False)[:3000]}\n"
        f"当前风格预设：{preset or 'default'}（执行器会自动应用）"
    )
    edited = _extract_code(_call_code([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]))
    if settings.llm_mock:
        edited = edited.rstrip("\n") + "\n# [mock] 已按指令应用修改\n"
    return edited


def repair_plot_code(code: str, error: str, summary: dict, preset: str | None = None) -> str:
    user_msg = (
        "请自动修复下面的科研绘图代码。只输出修复后的完整 Python 代码，不要解释。\n"
        f"运行错误：\n{error[-4000:]}\n\n"
        f"当前代码：\n```python\n{code}\n```\n\n"
        f"数据摘要：\n{json.dumps(summary, ensure_ascii=False)[:3000]}\n"
        f"当前风格预设：{preset or 'default'}（执行器会自动应用）"
    )
    repaired = _extract_code(_call_code([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]))
    if not repaired.strip():
        raise LLMError("自动修复返回了空代码")
    return repaired


# ---------------- mock 模式（无 API key 演示） ----------------

def _mock_reply(messages: list[dict]) -> str:
    user_text = messages[-1]["content"] if messages else ""
    low = user_text.lower()
    if "自动修复" in user_text or "修复" in user_text:
        if "plotly" in low or "交互" in user_text:
            return _MOCK_INTERACTIVE
        return _MOCK_BAR
    if "interactive" in low or "交互" in user_text:
        return _MOCK_INTERACTIVE
    if "hist" in low or "直方" in user_text:
        return _MOCK_HIST
    if "scatter" in low or "散点" in user_text:
        return _MOCK_SCATTER
    if "line" in low or "折线" in user_text:
        return _MOCK_LINE
    if "box" in low or "箱线" in user_text:
        return _MOCK_BOX
    return _MOCK_BAR


_MOCK_PRE = """import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
"""

_MOCK_BAR = _MOCK_PRE + """
x_col = df.columns[0]
y_cols = num_cols[:3] if num_cols else [df.columns[1]]
sns.set_style("whitegrid")
fig, ax = plt.subplots(figsize=(8, 5))
for i, c in enumerate(y_cols):
    ax.bar(np.arange(len(df)) + i * 0.25, df[c].fillna(0), width=0.25, label=str(c), alpha=0.85)
ax.set_xticks(np.arange(len(df)))
ax.set_xticklabels(df[x_col].astype(str), rotation=45, ha="right")
ax.set_xlabel(str(x_col))
ax.set_ylabel("value")
ax.set_title("数据可视化")
ax.legend()
fig.tight_layout()
"""

_MOCK_HIST = _MOCK_PRE + """
if not num_cols:
    raise SystemExit("无数值列")
fig, ax = plt.subplots(figsize=(8, 5))
for c in num_cols[:3]:
    sns.histplot(df[c].dropna(), kde=True, label=str(c), alpha=0.55, bins=30)
ax.set_xlabel("value")
ax.set_ylabel("count")
ax.set_title("数值列分布直方图")
ax.legend()
fig.tight_layout()
"""

_MOCK_SCATTER = _MOCK_PRE + """
if len(num_cols) < 2:
    raise SystemExit("数值列不足两列")
x, y = num_cols[0], num_cols[1]
fig, ax = plt.subplots(figsize=(8, 5))
sns.scatterplot(x=df[x], y=df[y], hue=df.columns[0], alpha=0.7, ax=ax)
ax.set_xlabel(str(x))
ax.set_ylabel(str(y))
ax.set_title(f"{x} vs {y} 散点图")
ax.legend()
fig.tight_layout()
"""

_MOCK_LINE = _MOCK_PRE + """
x_col = df.columns[0]
fig, ax = plt.subplots(figsize=(8, 5))
for c in num_cols[:4]:
    ax.plot(df[x_col], df[c].fillna(0), marker="o", markersize=3, label=str(c))
ax.set_xlabel(str(x_col))
ax.set_ylabel("value")
ax.set_title("折线图")
ax.legend()
fig.tight_layout()
"""

_MOCK_BOX = _MOCK_PRE + """
fig, ax = plt.subplots(figsize=(8, 5))
sns.boxplot(data=df[num_cols[:5]], ax=ax)
ax.set_title("箱线图")
ax.tick_params(axis="x", rotation=30)
fig.tight_layout()
"""

_MOCK_INTERACTIVE = """import plotly.express as px

num_cols = df.select_dtypes(include=["number"]).columns.tolist()
if len(num_cols) < 2:
    raise ValueError("交互散点图至少需要两列数值列")
x_col, y_col = num_cols[:2]
color_col = df.columns[0] if df.columns[0] not in num_cols else None
fig = px.scatter(df, x=x_col, y=y_col, color=color_col, title="交互式散点图")
fig.update_layout(template="plotly_white")
"""
