import json
import logging

from backend.app.logging_config import JsonFormatter


def _format(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def test_basic_fields_present():
    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="something happened", args=(), exc_info=None,
    )
    payload = _format(record)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "something happened"
    assert "timestamp" in payload


def test_extra_fields_are_included_as_top_level_keys():
    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="shift processed", args=(), exc_info=None,
    )
    record.call_id = "abc-123"
    record.duration_ms = 42.5

    payload = _format(record)

    assert payload["call_id"] == "abc-123"
    assert payload["duration_ms"] == 42.5


def test_exception_info_is_captured():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="test.logger", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )

    payload = _format(record)

    assert "ValueError: boom" in payload["exception"]


def test_non_json_serializable_extra_falls_back_to_str():
    class Unserializable:
        def __str__(self):
            return "<thing>"

    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="msg", args=(), exc_info=None,
    )
    record.weird = Unserializable()

    payload = _format(record)

    assert payload["weird"] == "<thing>"
