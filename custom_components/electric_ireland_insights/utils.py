from time import mktime


def date_to_unix(date_time):
    return str(int(mktime(date_time.timetuple())))
