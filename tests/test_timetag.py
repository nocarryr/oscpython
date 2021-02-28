import datetime
import pytz

from oscpython import TimeTag

TZ = pytz.timezone('US/Central')
UTC = pytz.utc

EPOCH = UTC.localize(datetime.datetime(1970, 1, 1))

def test_dt():
    dt_utc = datetime.datetime(2021, 2, 28, 9, 28, 13, 12345)
    dt_utc = UTC.localize(dt_utc)
    dt_local = TZ.normalize(dt_utc)
    ts1 = 1614504493.012345

    assert (dt_utc - EPOCH).total_seconds() == ts1

    tt1 = TimeTag.from_epoch(ts1)
    assert tt1.to_epoch() == ts1
    assert tt1.to_datetime_utc() == dt_utc.replace(tzinfo=None)
    assert tt1.to_datetime() == dt_local.replace(tzinfo=None)

    tt2 = TimeTag.from_datetime(dt_utc)
    assert tt2 == tt1
