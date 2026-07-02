from __future__ import annotations


VERIFICATION_STEP_NAMES = ('pipeline', 'expectations', 'doctor', 'tests', 'safety_scan')


def report_has_required_steps(
    report: dict[str, object] | None,
    required_steps: tuple[str, ...] = VERIFICATION_STEP_NAMES,
) -> bool | None:
    if not isinstance(report, dict):
        return None
    steps = report.get('steps')
    if not isinstance(steps, list):
        return False
    step_statuses: dict[str, object] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = step.get('name')
        if isinstance(name, str):
            step_statuses[name] = step.get('status')
    return all(step_statuses.get(name) == 'ok' for name in required_steps)


def report_status_matches_steps(report: dict[str, object] | None) -> bool | None:
    if not isinstance(report, dict):
        return None
    status = report.get('status')
    steps = report.get('steps')
    if status not in ('ok', 'fail') or not isinstance(steps, list):
        return None
    if report_has_required_steps(report) is not True:
        expected_status = 'fail'
    elif any(isinstance(step, dict) and step.get('status') != 'ok' for step in steps):
        expected_status = 'fail'
    else:
        expected_status = 'ok'
    return status == expected_status
