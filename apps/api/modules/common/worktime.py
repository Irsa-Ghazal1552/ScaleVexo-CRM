"""Working-calendar arithmetic used by the rule engine (CRM05/CRM06)."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def _calendar(workspace):
    tz = ZoneInfo(workspace.timezone or "UTC")
    days = {int(d) for d in (workspace.work_days or "0,1,2,3,4").split(",") if d.strip() != ""}
    return tz, days, workspace.work_start or time(9, 0), workspace.work_end or time(18, 0)


def working_minutes_between(workspace, start, end):
    """Minutes of configured working time between two aware datetimes."""
    if start is None or end is None or end <= start:
        return 0
    tz, days, ws, we = _calendar(workspace)
    start_l, end_l = start.astimezone(tz), end.astimezone(tz)
    # Anything older than 120 calendar days is simply "very long ago".
    if (end_l - start_l).days > 120:
        return 10**7
    total = 0
    day = start_l.date()
    while day <= end_l.date():
        if day.weekday() in days:
            open_at = datetime.combine(day, ws, tzinfo=tz)
            close_at = datetime.combine(day, we, tzinfo=tz)
            lo, hi = max(open_at, start_l), min(close_at, end_l)
            if hi > lo:
                total += int((hi - lo).total_seconds() // 60)
        day += timedelta(days=1)
    return total


def working_minutes_per_day(workspace):
    _, _, ws, we = _calendar(workspace)
    return max(1, (we.hour * 60 + we.minute) - (ws.hour * 60 + ws.minute))


def is_working_now(workspace, now):
    tz, days, ws, we = _calendar(workspace)
    local = now.astimezone(tz)
    return local.weekday() in days and ws <= local.time() < we
