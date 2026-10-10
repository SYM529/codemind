from services.evaluation_service import assess_generation


def test_function_coverage_and_valid_line_rate():
    result = assess_generation(
        generation_id="g1",
        structure={
            "totalLines": 10,
            "functions": [{"name": "add", "line": 1}, {"name": "multiply", "line": 5}],
        },
        comments=[
            {"functionName": "add", "line": 1},
            {"functionName": "unknown", "line": 99},
        ],
        duration_ms=1200,
        user_id=1,
    )
    assert result["functionCoverage"] == 0.5
    assert result["validLineRate"] == 0.5
    assert result["schemaValid"] is True
    assert result["durationMs"] == 1200


def test_no_functions_counts_as_full_coverage():
    result = assess_generation("g2", {"totalLines": 3, "functions": []}, [], 10)
    assert result["functionCoverage"] == 1
    assert result["validLineRate"] == 1
