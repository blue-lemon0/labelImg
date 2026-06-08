def ustr(x):
    """Python 3 unicode helper: always returns a string."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return str(x)
