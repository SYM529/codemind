from typing import Optional
from database import get_conn


def save_feedback(generation_id: str, user_id: int, rating: str, comment: str, created_at: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO feedback(generation_id,user_id,rating,comment,created_at) VALUES(?,?,?,?,?)",
        (generation_id, user_id, rating, comment, created_at),
    )
    conn.commit()
    conn.close()


def get_feedback_metrics(user_id: Optional[int] = None):
    conn = get_conn()
    if user_id:
        row = conn.execute(
            "SELECT SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END) AS helpful,"
            "SUM(CASE WHEN rating='needs_improvement' THEN 1 ELSE 0 END) AS needs_improvement"
            " FROM feedback WHERE user_id=?", (user_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END) AS helpful,"
            "SUM(CASE WHEN rating='needs_improvement' THEN 1 ELSE 0 END) AS needs_improvement"
            " FROM feedback"
        ).fetchone()
    conn.close()

    helpful = row["helpful"] or 0
    needs_improvement = row["needs_improvement"] or 0
    total = helpful + needs_improvement
    return {
        "total": total,
        "helpful": helpful,
        "needsImprovement": needs_improvement,
        "helpfulRate": None if total == 0 else round(helpful / total, 4),
    }
