import pydantic


def test_pydantic_is_available() -> None:
    assert pydantic.VERSION
