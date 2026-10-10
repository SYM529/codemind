import json
import re
import time
from typing import Callable, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from models import CommentItem, CommentResult

SYSTEM_MSG = "\n".join([
    "你是一名资深代码文档工程师。",
    "请根据用户提供的代码和结构分析结果完成指定任务：{task}。",
    "生成结果必须准确、简洁、可维护。",
    "不要臆测代码中不存在的业务行为；无法确定时使用中性描述。",
    "必须为每个识别出的函数生成一条注释。",
    "comment 字段在生成注释任务中必须是可以直接放到源代码函数前的完整注释；其他任务中可以为空字符串。",
    "如果提供了参考资料，请优先遵循其中的团队规范与约定，但不要编造资料中不存在的信息。",
    "只返回符合结构定义的 JSON，不要返回 Markdown 代码块。",
    "JSON 结构为：{schema}。",
])

# 前端传的是风格代码（jsdoc/docstring/default），这里翻译成模型能直接执行的格式说明
STYLE_GUIDES = {
    "jsdoc": "JSDoc / JavaDoc 风格：使用 /** ... */ 块注释，标注 @param 与 @returns",
    "docstring": "Python Docstring 风格：使用三引号文档字符串，标注 :param xxx: 与 :return:",
    "default": "简洁说明：只描述函数用途，不写参数与返回值",
}


def describe_style(style: str) -> str:
    """把风格代码映射为提示词里的中文说明，未知值一律按简洁说明处理。"""
    return STYLE_GUIDES.get((style or "").strip().lower(), STYLE_GUIDES["default"])


RESULT_SCHEMA = (
    '{"summary": string, "comments": [{"functionName": string, "line": number, '
    '"description": string, "parameters": [{"name": string, "description": string}], '
    '"returns": string, "comment": string}], "risks": [string], "suggestions": [string]}'
)

HUMAN_MSG = "\n".join([
    "编程语言：{language}",
    "任务：{task}",
    "注释风格：{style}",
    "代码结构分析：{structure}",
    "参考资料（可能为空）：",
    "{context}",
    "源代码：",
    "{code}",
])

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_MSG),
    ("human", HUMAN_MSG),
])


def _create_model() -> ChatOpenAI:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek AI 服务")
    return ChatOpenAI(
        api_key=DEEPSEEK_API_KEY,
        model=DEEPSEEK_MODEL,
        temperature=0.2,
        max_retries=2,
        base_url=DEEPSEEK_BASE_URL,
        stream_usage=True,
    )


def _parse_json_response(text: str):
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip("` \n")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("无法从模型输出中解析 JSON", cleaned, 0)


def _normalize(raw) -> CommentResult:
    if isinstance(raw, list):
        raw = {"comments": raw}
    if not isinstance(raw, dict):
        raw = {}
    raw_comments = raw.get("comments") or raw.get("functions") or []
    comments = []
    for item in (raw_comments if isinstance(raw_comments, list) else []):
        params = item.get("parameters") or []
        normalized_params = []
        for p in params:
            if isinstance(p, str):
                normalized_params.append({"name": p, "description": "函数输入参数"})
            elif isinstance(p, dict):
                normalized_params.append({"name": p.get("name", ""), "description": p.get("description", "")})
        comments.append(CommentItem(
            functionName=item.get("functionName") or item.get("name") or "anonymous",
            line=int(item.get("line") or 1),
            description=item.get("description") or "根据函数实现生成的代码说明",
            parameters=normalized_params,
            returns=item.get("returns") or "函数执行结果",
            comment=item.get("comment") or "",
        ))
    return CommentResult(
        summary=raw.get("summary") or "",
        comments=comments,
        risks=raw.get("risks") if isinstance(raw.get("risks"), list) else [],
        suggestions=raw.get("suggestions") if isinstance(raw.get("suggestions"), list) else [],
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def generate_comments(
    code: str,
    language: str,
    style: str,
    task: str,
    structure: dict,
    context: str = "",
    on_token: Optional[Callable[[str], None]] = None,
) -> dict:
    started = time.time()
    structure_text = json.dumps(structure, ensure_ascii=False)
    model = _create_model()
    chain = prompt | model
    input_data = {
        "code": code,
        "language": language,
        "style": describe_style(style),
        "task": task,
        "structure": structure_text,
        "context": context or "（无）",
        "schema": RESULT_SCHEMA,
    }

    usage_meta = None
    if on_token:
        chunks: list[str] = []
        async for chunk in chain.astream(input_data):
            if getattr(chunk, "usage_metadata", None):
                usage_meta = chunk.usage_metadata
            token = chunk.content if isinstance(chunk.content, str) else json.dumps(chunk.content or "")
            if token:
                chunks.append(token)
                on_token(token)
        content = "".join(chunks)
    else:
        resp = await chain.ainvoke(input_data)
        usage_meta = getattr(resp, "usage_metadata", None)
        content = resp.content if isinstance(resp.content, str) else json.dumps(resp.content)

    raw_result = _parse_json_response(content)
    result = _normalize(raw_result)

    duration_ms = int((time.time() - started) * 1000)
    real_input = (usage_meta or {}).get("input_tokens")
    real_output = (usage_meta or {}).get("output_tokens")
    input_tokens = real_input or _estimate_tokens(code + structure_text + task + language + style + context)
    output_tokens = real_output or _estimate_tokens(json.dumps(result.model_dump(), ensure_ascii=False))
    usage_source = "api" if (real_input and real_output) else "estimated"

    return {
        **result.model_dump(),
        "debug": {
            "model": DEEPSEEK_MODEL,
            "provider": "DeepSeek",
            "baseUrl": DEEPSEEK_BASE_URL,
            "durationMs": duration_ms,
            "promptVersion": "code-comments-v1",
            "outputFormat": "structured-json",
            "usage": {
                "estimatedInputTokens": input_tokens,
                "estimatedOutputTokens": output_tokens,
                "estimated": usage_source == "estimated",
                "source": usage_source,
            },
        },
    }

