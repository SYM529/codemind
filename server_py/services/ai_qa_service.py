"""项目级问答：复用 DeepSeek 调用封装，产出带来源编号的流式回答。

与单文件生成链路共用 ``_create_model`` / ``_estimate_tokens``，不新建 LLM 调用框架；
Prompt 强制"只依据给定片段、找不到就说无法确定"，引用编号由检索元数据在调用方映射，
模型文本里不直接出现行号，从源头避免伪造文件位置。
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate

from config import DEEPSEEK_MODEL
from services.ai_comment_service import _create_model, _estimate_tokens

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = "\n".join([
    "你是 CodeMind 的项目代码问答助手，负责基于检索到的项目代码回答用户问题。",
    "严格规则：",
    "1. 只能依据用户提供的代码片段回答，禁止使用片段之外的知识，禁止编造项目结构、文件路径或函数。",
    "2. 每个关键结论后标注来源编号，例如“登录逻辑在 [1] 中实现”。",
    "3. 如果片段中找不到答案，直接回答“根据当前项目代码无法确定”，不要猜测。",
    "4. 用简洁的中文回答，必要时引用关键代码说明。",
])

QA_HUMAN_TEMPLATE = "\n".join([
    "问题：{question}",
    "",
    "以下是从该项目检索到的代码片段（方括号是片段编号）：",
    "{context}",
])

_qa_prompt = ChatPromptTemplate.from_messages([
    ("system", QA_SYSTEM_PROMPT),
    ("human", QA_HUMAN_TEMPLATE),
])


async def stream_answer(
    question: str,
    context_text: str,
    on_token: Optional[Callable[[str], None]] = None,
) -> Dict:
    """流式生成回答。

    返回 ``{answer, durationMs, usage}``；``on_token`` 用于把 token 增量转发给 SSE。
    ``usage`` 的 input/output 优先取模型返回的真实 usage，否则用字符数估算。
    """
    started = time.time()
    model = _create_model()
    chain = _qa_prompt | model

    usage_meta = None
    chunks: list[str] = []
    async for chunk in chain.astream({"question": question, "context": context_text}):
        if getattr(chunk, "usage_metadata", None):
            usage_meta = chunk.usage_metadata
        token = chunk.content if isinstance(chunk.content, str) else ""
        if token:
            chunks.append(token)
            if on_token:
                on_token(token)

    answer = "".join(chunks).strip()
    duration_ms = int((time.time() - started) * 1000)

    real_input = (usage_meta or {}).get("input_tokens")
    real_output = (usage_meta or {}).get("output_tokens")
    input_tokens = real_input or _estimate_tokens(question + context_text)
    output_tokens = real_output or _estimate_tokens(answer)
    source = "api" if (real_input and real_output) else "estimated"

    return {
        "answer": answer,
        "durationMs": duration_ms,
        "usage": {
            "model": DEEPSEEK_MODEL,
            "estimatedInputTokens": input_tokens,
            "estimatedOutputTokens": output_tokens,
            "source": source,
        },
    }
