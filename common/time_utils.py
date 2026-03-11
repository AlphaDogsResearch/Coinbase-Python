import time
import datetime


def current_milli_time():
    return int(time.time() * 1000)


def convert_epoch_time_to_datetime_millis(timestamp:float):
    return datetime.datetime.fromtimestamp(timestamp / 1000)