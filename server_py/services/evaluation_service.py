from typing import Any, Dict, Optional
from database import get_conn


def assess_generation(
    generation_id: str,
    structure: dict,
    comments: list,
    duration_ms: int,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    functions = structure.get("functions") or []
    total_lines = structure.get("totalLines", 0)

    valid_line_comments = [
        c for c in comments
        if isinstance(c.get("line"), int) and 0 < c["line"] <= (total_lines or 999999999)
    ]
    covered = [
        f for f in functions
        if any(c.get("functionName") == f["name"] or c.get("line") == f["line"] for c in comments)
    ]

    fc = len(covered) / len(functions) if functions else 1.0
    vl = len(valid_line_comments) / len(comments) if comments else 1.0

    return {
        "generationId": generation_id,
        "userId": user_id,
        "schemaValid": True,
        "functionCount": len(functions),
        "commentCount": len(comments),
        "functionCoverage": round(fc, 4),
        "validLineRate": round(vl, 4),
        "durationMs": duration_ms if duration_ms is not None else 0,
    }


def record_evaluation(ev: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO evaluations"
        "(generation_id,user_id,schema_valid,function_count,comment_count,function_coverage,valid_line_rate,duration_ms,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (
            ev["generationId"], ev.get("userId"),
            1 if ev["schemaValid"] else 0,
            ev["functionCount"], ev["commentCount"],
            ev["functionCoverage"], ev["validLineRate"],
            ev["durationMs"], ev.get("createdAt", ""),
        ),
    )
    conn.commit()
    conn.close()


def get_evaluation_metrics(user_id: Optional[int] = None):
    conn = get_conn()
    if user_id:
        rows = conn.execute("SELECT * FROM evaluations WHERE user_id=?", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM evaluations").fetchall()
    conn.close()

    if not rows:
        return {
            "generations": 0,
            "schemaSuccessRate": 0,
            "averageFunctionCoverage": 0,
            "averageValidLineRate": 0,
            "averageDurationMs": 0,
        }

    n = len(rows)
    return {
        "generations": n,
        "schemaSuccessRate": round(sum(1 for r in rows if r["schema_valid"]) / n, 4),
        "averageFunctionCoverage": round(sum(r["function_coverage"] for r in rows) / n, 4),
        "averageValidLineRate": round(sum(r["valid_line_rate"] for r in rows) / n, 4),
        "averageDurationMs": round(sum(r["duration_ms"] for r in rows) / n),
    }
