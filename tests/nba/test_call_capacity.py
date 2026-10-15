from datetime import UTC, datetime, time, timedelta

from kept.nba.ranking import CallCapacity


class Ctx:  # the fields CallCapacity reads
    time_zone = "America/Toronto"
    permitted_call_start_local = time(8, 0)
    permitted_call_end_local = time(21, 0)
    sunday_contact_permitted = False


def test_calls_fill_an_hour_then_move_to_the_next_one_with_capacity() -> None:
    # Thursday 15 Oct 2026, bank time = customer time; one call an hour at 08:00, none at 09:00, two at 10:00
    book = CallCapacity({(3, 8): 1, (3, 10): 2}, tz="America/Toronto", length=timedelta(hours=2))
    first = (datetime(2026, 10, 15, 12, 0, tzinfo=UTC), datetime(2026, 10, 15, 14, 0, tzinfo=UTC))  # 08:00 EDT
    a, b, c, d = (book.book(Ctx(), first)[0] for _ in range(4))  # type: ignore[arg-type]
    assert a == first[0]  # 08:00
    assert b == c == datetime(2026, 10, 15, 14, 0, tzinfo=UTC)  # 10:00, twice
    assert d.date() > first[0].date() or d == first[0]  # then a later day (or, with none left, the first slot)
