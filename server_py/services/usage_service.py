from typing import Optional
from database import get_conn


def record_usage(
    generation_id: str,
    user_id: Optional[int],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    created_at: str,
    token_source: str = "unknown",
):
    conn = get_conn()
    conn.execute(
        "INSERT INTO usage_records(generation_id,user_id,model,estimated_input_tokens,estimated_output_tokens,estimated_cost_usd,token_source,created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (generation_id, user_id, model, input_tokens, output_tokens, cost_usd, token_source, created_at),
    )
    conn.commit()
    conn.close()


def get_usage_metrics(user_id: Optional[int] = None):
    conn = get_conn()
    if user_id:
        row = conn.execute(
            "SELECT COUNT(*) AS requests,"
            "COALESCE(SUM(estimated_input_tokens),0) AS input_tokens,"
            "COALESCE(SUM(estimated_output_tokens),0) AS output_tokens,"
            "COALESCE(SUM(estimated_cost_usd),0) AS cost_usd"
            " FROM usage_records WHERE user_id=?", (user_id,),
        ).fetchone()
        source_rows = conn.execute(
            "SELECT token_source, COUNT(*) AS c FROM usage_records WHERE user_id=? GROUP BY token_source",
            (user_id,),
        ).fetchall()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS requests,"
            "COALESCE(SUM(estimated_input_tokens),0) AS input_tokens,"
            "COALESCE(SUM(estimated_output_tokens),0) AS output_tokens,"
            "COALESCE(SUM(estimated_cost_usd),0) AS cost_usd"
            " FROM usage_records"
        ).fetchone()
        source_rows = conn.execute(
            "SELECT token_source, COUNT(*) AS c FROM usage_records GROUP BY token_source"
        ).fetchall()
    conn.close()

    source_breakdown = {r["token_source"]: r["c"] for r in source_rows}
    # 仅当不存在任何一条“模型返回真实 usage”的记录时，才标记为估算口径
    estimated = source_breakdown.get("api", 0) == 0
    return {
        "requests": row["requests"],
        "estimatedInputTokens": row["input_tokens"],
        "estimatedOutputTokens": row["output_tokens"],
        "estimatedCostUsd": row["cost_usd"],
        "estimated": estimated,
        "tokenSourceBreakdown": source_breakdown,
    }
