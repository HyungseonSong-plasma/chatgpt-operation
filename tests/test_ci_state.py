from chatgpt_operation.github.ci_state import synthesize_ci_state


def test_actions_success_overrides_empty_legacy_pending_surface():
    assert synthesize_ci_state(
        {"state":"pending","statuses":[]},
        {
            "total_count":1,
            "check_runs":[
                {"status":"completed","conclusion":"success","name":"CI"}
            ],
        },
    )=="success"


def test_in_progress_check_run_is_pending():
    assert synthesize_ci_state(
        {"state":"pending","statuses":[]},
        {
            "total_count":1,
            "check_runs":[
                {"status":"in_progress","conclusion":None,"name":"CI"}
            ],
        },
    )=="pending"


def test_failed_check_run_fails_closed():
    assert synthesize_ci_state(
        {"state":"pending","statuses":[]},
        {
            "total_count":1,
            "check_runs":[
                {"status":"completed","conclusion":"failure","name":"CI"}
            ],
        },
    )=="failure"


def test_legacy_pending_context_still_blocks_actions_success():
    assert synthesize_ci_state(
        {
            "state":"pending",
            "statuses":[{"context":"external","state":"pending"}],
        },
        {
            "total_count":1,
            "check_runs":[
                {"status":"completed","conclusion":"success","name":"CI"}
            ],
        },
    )=="pending"


def test_legacy_failure_dominates_actions_success():
    assert synthesize_ci_state(
        {
            "state":"failure",
            "statuses":[{"context":"external","state":"failure"}],
        },
        {
            "total_count":1,
            "check_runs":[
                {"status":"completed","conclusion":"success","name":"CI"}
            ],
        },
    )=="failure"


def test_no_ci_surfaces_is_unknown():
    assert synthesize_ci_state(
        {"state":"pending","statuses":[]},
        {"total_count":0,"check_runs":[]},
    )=="unknown"
