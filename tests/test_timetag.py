import datetime
import pytest

from oscpython import TimeTag

UTC = datetime.timezone.utc
TZ = datetime.datetime.now(UTC).astimezone().tzinfo

EPOCH = datetime.datetime(1970, 1, 1, tzinfo=UTC)
MILLISECOND = datetime.timedelta(microseconds=1000)

def test_dt():
    dt_utc = datetime.datetime(2021, 2, 28, 9, 28, 13, 12345, tzinfo=UTC)
    dt_local = dt_utc.astimezone(TZ)
    ts1 = 1614504493.012345

    assert (dt_utc - EPOCH).total_seconds() == ts1

    tt1 = TimeTag.from_epoch(ts1)
    assert tt1.to_epoch() == pytest.approx(ts1)
    assert tt1.to_datetime_utc() == dt_utc.replace(tzinfo=None)
    assert tt1.to_datetime() == dt_local.replace(tzinfo=None)

    tt2 = TimeTag.from_datetime(dt_utc)
    assert tt2 == tt1

    now_dt, now_tt = datetime.datetime.now(), TimeTag.now()
    now_dtu, now_ttu = datetime.datetime.utcnow(), TimeTag.utcnow()

    assert now_dt.timestamp() == pytest.approx(now_tt.to_epoch())
    assert now_dtu.timestamp() == pytest.approx(now_ttu.to_epoch())

def test_ops(faker):
    assert TimeTag.Immediately == TimeTag(seconds=0, fraction=1)
    assert TimeTag(seconds=0, fraction=1) == TimeTag.Immediately

    for _ in range(100):
        dt1 = faker.date_time()
        ts1 = TimeTag.from_datetime(dt1)

        assert ts1 > TimeTag.Immediately
        assert ts1 >= TimeTag.Immediately
        assert TimeTag.Immediately < ts1
        assert TimeTag.Immediately <= ts1
        assert TimeTag(seconds=ts1.seconds, fraction=ts1.fraction) == ts1

        assert ts1 == dt1

        for dt2 in [dt1 + MILLISECOND, dt1 - MILLISECOND, faker.date_time()]:
            ts2 = TimeTag.from_datetime(dt2)
            assert ts2 == dt2

            assert ts2 > TimeTag.Immediately
            assert ts2 >= TimeTag.Immediately
            assert TimeTag.Immediately < ts2
            assert TimeTag.Immediately <= ts2

            assert ts2 != ts1
            assert ts2 != dt1
            assert ts1 != ts2
            assert ts1 != dt2

            if dt1 > dt2:
                assert ts1 > ts2
                assert dt1 > ts2
                assert ts1 >= ts2
                assert dt1 >= ts2
                assert ts2 < ts1
                assert ts2 < dt1
                assert ts2 <= ts1
                assert ts2 <= dt1
            else:
                assert ts1 < ts2
                assert dt1 < ts2
                assert ts1 <= ts2
                assert dt1 <= ts2
                assert ts2 > ts1
                assert ts2 > dt1
                assert ts2 >= ts1
                assert ts2 >= dt1
