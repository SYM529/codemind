import json
from typing import Optional
from database import get_conn


def save_generation(
    generation_id: str,
    user_id: Optional[int],
    language: str,
    task: str,
    style: str,
    code: str,
    summary: str,
    comments: list,
    risks: list,
    suggestions: list,
    debug: dict,
    created_at: str,
):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO generations"
        "(generation_id,user_id,language,task,style,code,summary,comments_json,risks_json,suggestions_json,debug_json,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            generation_id, user_id, language, task, style, code, summary,
            json.dumps(comments, ensure_ascii=False),
            json.dumps(risks, ensure_ascii=False),
            json.dumps(suggestions, ensure_ascii=False),
            json.dumps(debug, ensure_ascii=False),
            created_at,
        ),
    )
    conn.commit()
    conn.close()


def list_generations(
    page: int = 1,
    page_size: int = 10,
    language: Optional[str] = None,
    task: Optional[str] = None,
    user_id: Optional[int] = None,
):
    filters = []
    values = []
    if language:
        filters.append("language=?")
        values.append(language)
    if task:
        filters.append("task=?")
        values.append(task)
    if user_id:
        filters.append("user_id=?")
        values.append(user_id)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM generations {where}", values).fetchone()["c"]
    start = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM generations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        values + [page_size, start],
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "generationId": r["generation_id"],
            "language": r["language"],
            "task": r["task"],
            "style": r["style"],
            "code": r["code"],
            "summary": r["summary"],
            "comments": json.loads(r["comments_json"]),
            "risks": json.loads(r["risks_json"]),
            "suggestions": json.loads(r["suggestions_json"]),
            "debug": json.loads(r["debug_json"]),
            "createdAt": r["created_at"],
        })
    return {"items": items, "page": page, "pageSize": page_size, "total": total}
