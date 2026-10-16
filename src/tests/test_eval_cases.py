"""
Live Trajectory Evaluation Suite (TC-01 through TC-14).
Marked @pytest.mark.eval, excluded by default.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
import pytest

TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"
with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
    ALL_CASES = json.load(f)

CASE_MAP = {tc["id"]: tc for tc in ALL_CASES}


def run_eval_trajectory_with_bootstrap(
    handler: Any,
    test_case: Dict[str, Any],
    case_map: Dict[str, Dict[str, Any]],
    thread_id: str,
    user_id: str = "eval_harness",
) -> Dict[str, Any]:
    """Execute evaluation case with multi-turn prerequisite bootstrap on the same thread."""
    follow_up_to = test_case.get("follow_up_to")
    if follow_up_to:
        if follow_up_to not in case_map:
            raise ValueError(
                f"Unknown or missing prerequisite scenario '{follow_up_to}' for test case '{test_case.get('id')}'"
            )
        parent_case = case_map[follow_up_to]
        handler.invoke_with_trajectory(
            thread_id=thread_id,
            question=parent_case["question"],
            user_id=user_id,
        )

    return handler.invoke_with_trajectory(
        thread_id=thread_id,
        question=test_case["question"],
        user_id=user_id,
    )


@pytest.mark.eval
@pytest.mark.parametrize("test_case", ALL_CASES, ids=[tc["id"] for tc in ALL_CASES])
def test_eval_case(test_case):
    """Run trajectory evaluation for a single test case with lazy imports and prerequisite bootstrapping."""
    from src.handler import ChatbotHandler
    from src.databases import conv_db, query_engine
    from src.tests.judges import evaluate_case

    handler = ChatbotHandler()
    tc_id = test_case["id"]
    thread_id = f"eval-{tc_id}-{uuid.uuid4().hex[:8]}"

    try:
        res_obj = run_eval_trajectory_with_bootstrap(
            handler=handler,
            test_case=test_case,
            case_map=CASE_MAP,
            thread_id=thread_id,
        )
        response = res_obj["answer"]
        tool_calls = res_obj.get("tool_calls", [])

        # Run ground truth query if applicable
        gt_query = test_case.get("ground_truth_query")
        gt_data = None
        if gt_query:
            try:
                result = query_engine.execute_query(gt_query)
                gt_data = str(result)
            except Exception as e:
                gt_data = f"ERROR: {e}"

        # Evaluate against deterministic rubric
        eval_result = evaluate_case(
            response=response,
            test_case=test_case,
            tool_calls=tool_calls,
            ground_truth_data=gt_data,
        )

        assert eval_result["pass"] is True, (
            f"Case {tc_id} failed evaluation.\n"
            f"Total score: {eval_result['total_score']}/{eval_result['max_possible']}\n"
            f"Details: {eval_result['scores']}\n"
            f"Response: {response}"
        )
    finally:
        conv_db.delete_conversation(thread_id)
