from datetime import datetime


DIFFICULTY_POINTS = {
    "Low": 5,
    "Medium": 15,
    "High": 25,
}


def calculate_risk(
    deadline: datetime,
    difficulty: str,
    pending_tasks: int,
    status: str,
) -> int:
    days_remaining = max((deadline - datetime.now()).days, 0)

    if days_remaining <= 1:
        time_points = 55
    elif days_remaining <= 3:
        time_points = 40
    elif days_remaining <= 7:
        time_points = 25
    else:
        time_points = 10

    difficulty_points = DIFFICULTY_POINTS.get(difficulty, 15)
    workload_points = min(pending_tasks * 3, 15)
    status_points = 0 if status == "Completed" else 10

    return min(
        time_points
        + difficulty_points
        + workload_points
        + status_points,
        100,
    )


def risk_label(score: int) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 35:
        return "Moderate"
    return "Low"