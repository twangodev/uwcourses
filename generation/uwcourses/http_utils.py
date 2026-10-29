from fake_useragent import UserAgent

_ua = UserAgent()
_user_agent = _ua.chrome


def get_user_agent() -> str:
    """Returns a consistent browser user agent string for this process."""
    return _user_agent
