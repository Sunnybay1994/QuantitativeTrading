"""Literature-fixed calendar allocation; no price input or fitted threshold."""
import datetime as dt
from collections import defaultdict

import polars as pl


def calendar_targets(calendar, *, start, end, name, equity_symbol, bond_symbol,
                     sleeve=0.25, first_sessions=3, calendar_revisions=()):
    if name not in {"calendar_bond", "calendar_cash", "static_calendar_exposure", "bond_only"}:
        raise ValueError("Unknown calendar rule")
    if not 0 < sleeve <= 1 or first_sessions < 1:
        raise ValueError("Invalid calendar allocation")
    dates = calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))["date"].sort().to_list()
    if len(dates) != len(set(dates)):
        raise ValueError("Duplicate exchange sessions")
    # Require complete boundary months and a prior/next exchange session. Never
    # infer a month-end from a price sample's final row or a truncated calendar.
    if not dates or dates[0] >= start.replace(day=1):
        raise ValueError("Calendar requires prior-month coverage")
    next_month = (end.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    if dates[-1] < next_month:
        raise ValueError("Calendar requires next-month coverage")
    months = defaultdict(list)
    for date in dates:
        months[date.year, date.month].append(date)
    for revision in calendar_revisions:
        if revision["announced_date"] >= revision["session"]:
            raise ValueError("Calendar revision must precede affected session")
        if revision["final_open"] != (revision["session"] in dates):
            raise ValueError("Calendar revision conflicts with actual sessions")
    previous_active = None
    rows, schedule = [], []
    for prior, day in zip(dates, dates[1:]):
        if not start <= day <= end:
            continue
        # Calendar-only orders may be prepared on non-trading days. In
        # particular, a holiday extension announced DURING a closure must not
        # retroactively change the last trading day's decision before it.
        decision_date = day - dt.timedelta(days=1)
        month = set(months[day.year, day.month])
        for revision in calendar_revisions:
            session = revision["session"]
            if (session.year, session.month) == (day.year, day.month) and decision_date < revision["announced_date"]:
                if revision["previous_open"]:
                    month.add(session)
                else:
                    month.discard(session)
        month = sorted(month)
        if len(month) <= first_sessions + 1:
            raise ValueError("Insufficient calendar month")
        active = day in month[:first_sessions] or day == month[-1]
        fraction = (first_sessions + 1) / len(month)
        if name.startswith("calendar_"):
            submit = previous_active is None or active != previous_active
            eq = sleeve if active else 0.0
            bond = 1.0 - eq if name == "calendar_bond" else 1.0 - sleeve
        elif name == "static_calendar_exposure":
            submit = previous_active is None or day == month[0]
            eq, bond = sleeve * fraction, 1.0 - sleeve * fraction
        else:
            submit = previous_active is None
            eq, bond = 0.0, 1.0
        schedule.append(dict(date=day, as_of=prior, decision_date=decision_date, active=active,
                             calendar_sessions=len(month), calendar_fraction=fraction,
                             equity_target=eq, bond_target=bond, submit=submit))
        if submit:
            for symbol, weight in [(equity_symbol, eq), (bond_symbol, bond)]:
                rows.append(dict(as_of=prior, execution_date=day, symbol=symbol,
                                 strategy=name, strategy_version="v1", weight=weight))
        previous_active = active
    if not rows:
        raise ValueError("No calendar targets")
    return pl.DataFrame(rows), pl.DataFrame(schedule)
