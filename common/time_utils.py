import time
import datetime


def current_milli_time():
    return int(time.time() * 1000)


def get_past_epoch_milliseconds(hours:int):
    # seconds * 1000 = milliseconds
    seconds_ago = time.time() - (hours * 60 * 60)
    return int(seconds_ago * 1000)


def get_past_epoch_milliseconds_offset(hours: int):
    # 1. Get current time in seconds
    now_seconds = time.time()

    # 2. Round down to the start of the current hour
    # 3600 seconds in an hour
    current_hour_start = (now_seconds // 3600) * 3600

    # 3. Subtract the offset
    past_hour_start = current_hour_start - (hours * 60 * 60)

    # 4. Return as millisecond integer
    return int(past_hour_start * 1000)


def convert_epoch_time_to_datetime_millis(timestamp:float):
    return datetime.datetime.fromtimestamp(timestamp / 1000)