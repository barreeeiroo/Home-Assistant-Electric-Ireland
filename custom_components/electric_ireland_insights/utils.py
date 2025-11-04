from datetime import datetime


def date_to_unix(date_time: datetime) -> str:
    """Convert a datetime object to Unix timestamp string.

    Args:
        date_time: Datetime object to convert (should be timezone-aware)

    Returns:
        Unix timestamp as a string

    Note:
        If the datetime is timezone-aware, it will be converted to UTC first.
        If the datetime is naive, it will be treated as UTC.
    """
    # If timezone-aware, convert to UTC timestamp
    if date_time.tzinfo is not None:
        return str(int(date_time.timestamp()))
    else:
        # If naive, treat as UTC
        from time import mktime
        return str(int(mktime(date_time.timetuple())))
