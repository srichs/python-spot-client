import asyncio
import datetime
import json
import logging
import math
import types
import sys
from pathlib import Path

import httpx
import pytest

# Ensure the project root is on the path so that ``spot_api`` can be imported when the
# package is not installed in editable mode.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spot_api import (  # noqa: E402
    SpotApi,
    SpotBatteryState,
    SpotDeviceType,
    SpotFeed,
    SpotFeedStatus,
    SpotFeedType,
    SpotMessage,
    SpotMessageType,
    SpotRequestResult,
    SpotRequestStatus,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _parse_datetime,
)

import spot_api.client  # noqa: E402


UTC = datetime.timezone.utc


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("Y", True),
        ("n", False),
        ("TRUE", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("", False),
        (None, False),
    ],
)
def test_coerce_bool_handles_common_representations(value, expected):
    assert _coerce_bool(value) is expected


def test_models_module_exports_coerce_bool_in_all():
    assert "_coerce_bool" in spot_api.models.__all__


def test_spot_api_defaults_to_no_password_for_unprotected_feed():
    api = SpotApi([("feed123", None)])

    feed = api.get_feed()
    payload = api._get_base_payload(feed)

    assert feed.password == ""
    assert "feedPassword" not in payload


def test_spot_api_accepts_multiple_feed_ids_and_passwords():
    api = SpotApi([("feed-one", "secret"), ("feed-two", None)])

    feed_one = api.get_feed("feed-one")
    feed_two = api.get_feed("feed-two")

    payload_one = api._get_base_payload(feed_one)
    payload_two = api._get_base_payload(feed_two)

    assert payload_one["feedPassword"] == "secret"
    assert "feedPassword" not in payload_two


def test_spot_api_requires_password_in_each_feed_entry():
    with pytest.raises(ValueError):
        SpotApi([("feed-one", "secret"), ("feed-two",)])


def test_spot_api_rejects_duplicate_feed_ids():
    with pytest.raises(ValueError, match="Duplicate feed ID configured"):
        SpotApi([("feed-one", "secret"), ("feed-one", "other")])


def test_spot_api_requires_non_empty_feed_list():
    with pytest.raises(ValueError):
        SpotApi([])


def test_spot_api_requires_feed_list_argument():
    with pytest.raises(ValueError):
        SpotApi(None)  # type: ignore[arg-type]


def test_spot_api_rejects_non_iterable_feed_entry():
    with pytest.raises(ValueError):
        SpotApi([123])  # type: ignore[list-item]


def test_spot_api_supports_custom_base_endpoint():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi(
        [("feed", None)],
        client=client,
        base_endpoint="https://example.test/custom/base",
    )

    asyncio.run(api.request())

    assert client.request_history
    url, params, headers = client.request_history[0]
    assert url == "https://example.test/custom/base/feed/message.json"
    assert params is not None
    assert headers is None


def test_average_location_with_empty_messages_returns_none():
    assert SpotApi.average_location([]) is None


def test_average_location_with_messages_computes_average():
    message_one = SpotMessage(latitude=10.0, longitude=20.0)
    message_two = SpotMessage(latitude=30.0, longitude=40.0)

    result = SpotApi.average_location([message_one, message_two])

    assert result is not None
    avg_lat, avg_lon = result

    assert math.isclose(avg_lat, 20.0)
    assert math.isclose(avg_lon, 30.0)


def test_average_location_with_single_message_returns_same_coordinates():
    message = SpotMessage(latitude=12.3456, longitude=-78.9)

    result = SpotApi.average_location([message])

    assert result is not None
    assert result == pytest.approx((12.3456, -78.9))


def test_average_location_ignores_origin_coordinates():
    valid_message = SpotMessage(latitude=10.0, longitude=20.0)
    placeholder_message = SpotMessage()

    result = SpotApi.average_location([valid_message, placeholder_message])

    assert result is not None
    assert result == pytest.approx((10.0, 20.0))


def test_average_location_optionally_includes_origin():
    origin_message = SpotMessage(latitude=0.0, longitude=0.0)

    result = SpotApi.average_location([origin_message], allow_origin=True)

    assert result == pytest.approx((0.0, 0.0))


def test_average_location_returns_none_when_no_valid_coordinates():
    message_one = SpotMessage(latitude=None, longitude=None)
    message_two = SpotMessage(latitude=float("nan"), longitude=float("nan"))

    assert SpotApi.average_location([message_one, message_two]) is None


def test_add_message_falls_back_to_unix_time_when_datetime_missing():
    feed = SpotFeed("feed", "")
    unix_time = 1_700_000_000
    message = SpotMessage(unix_time=unix_time)

    feed._add_message("device", message)

    expected = datetime.datetime.fromtimestamp(unix_time, tz=UTC)
    assert feed.devices["device"][0] is message
    assert message.date_time == expected


@pytest.mark.parametrize(
    "raw, expected, warns",
    [
        ("good", SpotBatteryState.GOOD, False),
        ("GOOD", SpotBatteryState.GOOD, False),
        ("Low", SpotBatteryState.LOW, False),
        ("critical", SpotBatteryState.CRITICAL, False),
        ("Charging", SpotBatteryState.CHARGING, False),
        ("replace", SpotBatteryState.REPLACE, False),
        ("", SpotBatteryState.UNKNOWN_STATE, False),
        (None, SpotBatteryState.UNKNOWN_STATE, False),
        ("bogus", SpotBatteryState.UNKNOWN_STATE, True),
    ],
)
def test_spot_battery_state_from_str_variants(raw, expected, warns, caplog):
    with caplog.at_level(logging.WARNING):
        assert SpotBatteryState.from_str(raw) is expected

    if warns:
        assert "battery state" in caplog.text
    else:
        assert "battery state" not in caplog.text


@pytest.mark.parametrize(
    "raw, expected, warns",
    [
        ("shared_page", SpotFeedType.SHARED_PAGE, False),
        ("Shared Page", SpotFeedType.SHARED_PAGE, False),
        ("private_page", SpotFeedType.PRIVATE_PAGE, False),
        ("Adventure", SpotFeedType.ADVENTURE, False),
        ("enterprise", SpotFeedType.ENTERPRISE_ACCOUNT, False),
        ("", SpotFeedType.UNKNOWN_TYPE, False),
        ("unexpected", SpotFeedType.UNKNOWN_TYPE, True),
    ],
)
def test_spot_feed_type_from_str_variants(raw, expected, warns, caplog):
    with caplog.at_level(logging.WARNING):
        assert SpotFeedType.from_str(raw) is expected

    if warns:
        assert "feed type" in caplog.text
    else:
        assert "feed type" not in caplog.text


@pytest.mark.parametrize(
    "raw, expected, warns",
    [
        ("SPOTTRACE", SpotDeviceType.SPOT_TRACE, False),
        ("Spot Trace", SpotDeviceType.SPOT_TRACE, False),
        ("SPOT GEN3", SpotDeviceType.SPOT_GEN3, False),
        ("gen4", SpotDeviceType.SPOT_GEN4, False),
        ("SpotX", SpotDeviceType.SPOT_X, False),
        ("", SpotDeviceType.UNKNOWN_DEVICE, False),
        (None, SpotDeviceType.UNKNOWN_DEVICE, False),
        ("mystery", SpotDeviceType.UNKNOWN_DEVICE, True),
    ],
)
def test_spot_device_type_from_str_variants(raw, expected, warns, caplog):
    with caplog.at_level(logging.WARNING):
        assert SpotDeviceType.from_str(raw or "") is expected

    if warns:
        assert "device type" in caplog.text
    else:
        assert "device type" not in caplog.text


@pytest.mark.parametrize(
    "raw, expected, warns",
    [
        ("ACTIVE", SpotFeedStatus.ACTIVE, False),
        ("inactive", SpotFeedStatus.INACTIVE, False),
        (None, SpotFeedStatus.UNKNOWN_STATUS, False),
        ("UNKNOWN", SpotFeedStatus.UNKNOWN_STATUS, True),
    ],
)
def test_spot_feed_status_from_str_variants(raw, expected, warns, caplog):
    with caplog.at_level(logging.WARNING):
        assert SpotFeedStatus.from_str(raw) is expected

    if warns:
        assert "feed status" in caplog.text
    else:
        assert "feed status" not in caplog.text


@pytest.mark.parametrize(
    "value, expected",
    [
        ("3.14", 3.14),
        (42, 42.0),
        (None, None),
        ("not-a-float", None),
    ],
)
def test_coerce_float_handles_invalid_values(value, expected, caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce_float(value)

    assert result == expected
    if expected is None and value not in (None,):
        assert "convert value" in caplog.text


@pytest.mark.parametrize(
    "value, expected",
    [
        ("10", 10),
        (5.8, 5),
        ("not-an-int", None),
        (None, None),
    ],
)
def test_coerce_int_handles_invalid_values(value, expected, caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce_int(value)

    assert result == expected
    if expected is None:
        assert "convert value" in caplog.text


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "2023-07-14T16:30:05+0000",
            datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC),
        ),
        ("2023-07-14T16:30:05", datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC)),
        ("2023-07-14T16:30:05Z", datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC)),
        (
            "2023-07-14T16:30:05-0700",
            datetime.datetime(2023, 7, 14, 23, 30, 5, tzinfo=UTC),
        ),
        (None, None),
    ],
)
def test_parse_datetime_handles_variants(raw, expected):
    assert _parse_datetime(raw) == expected


def test_parse_datetime_logs_invalid_values(caplog):
    with caplog.at_level(logging.WARNING):
        assert _parse_datetime("invalid-date") is None

    assert "Unable to parse datetime" in caplog.text


def test_spot_message_from_json_coerces_types():
    message_json = {
        "@clientUnixTime": "1689347405",
        "id": "123",
        "messengerId": "ABC123",
        "messengerName": "Test Device",
        "unixTime": "1689347405",
        "messageType": "TRACK",
        "latitude": "34.05",
        "longitude": "-118.25",
        "modelId": "SPOTTRACE",
        "showCustomMsg": "Y",
        "dateTime": "2023-07-14T16:30:05+0000",
        "batteryState": "GOOD",
        "hidden": "0",
        "altitude": "123",
    }

    message = SpotMessage.from_json(message_json)

    assert message.id == 123
    assert message.messenger_id == "ABC123"
    assert message.message_type is SpotMessageType.TRACK
    assert math.isclose(message.latitude, 34.05)
    assert math.isclose(message.longitude, -118.25)
    assert message.model_id.name == "SPOT_TRACE"
    assert message.show_custom_message is True
    assert message.date_time == datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC)
    assert message.battery_state is SpotBatteryState.GOOD
    assert message.hidden == 0
    assert message.altitude == 123


def test_spot_message_from_json_clamps_invalid_coordinates():
    message_json = {
        "@clientUnixTime": "1689347405",
        "id": "1",
        "messengerId": "ABC123",
        "messengerName": "Test Device",
        "unixTime": "1689347405",
        "messageType": "TRACK",
        "latitude": "200",
        "longitude": "-200",
        "batteryState": "GOOD",
    }

    message = SpotMessage.from_json(message_json)

    assert message.latitude == 0.0
    assert message.longitude == 0.0


def test_spot_message_get_short_datetime_prefers_datetime():
    message = SpotMessage(
        date_time=datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC)
    )

    assert message.get_short_datetime() == datetime.datetime(
        2023, 7, 14, 16, 30, 5, tzinfo=UTC
    ).strftime("%Y-%m-%d %H:%M:%S")


def test_spot_message_get_short_datetime_falls_back_to_unix_time():
    unix_timestamp = int(
        datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC).timestamp()
    )
    message = SpotMessage(unix_time=str(unix_timestamp))

    assert message.get_short_datetime() == datetime.datetime(
        2023, 7, 14, 16, 30, 5, tzinfo=UTC
    ).strftime("%Y-%m-%d %H:%M:%S")


def test_spot_message_get_short_datetime_handles_missing_timestamps():
    message = SpotMessage()

    assert message.get_short_datetime() == ""


def test_spot_message_get_location_formats_values():
    message = SpotMessage(latitude=34.05, longitude=-118.25, altitude=100)

    assert message.get_location() == "34.05, -118.25, 100"


def test_spot_feed_from_json_builds_devices():
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {
                    "name": "Demo Feed",
                    "description": "A demo",
                    "status": "ACTIVE",
                    "usage": "5",
                    "daysRange": "7",
                    "detailedMessageShown": True,
                    "type": "Shared Page",
                },
                "count": "1",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347405",
                            "id": "321",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347405",
                            "messageType": "TRACK",
                            "latitude": "34.05",
                            "longitude": "-118.25",
                            "dateTime": "2023-07-14T16:30:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }

    feed.from_json(response)

    assert feed.name == "Demo Feed"
    assert feed.description == "A demo"
    assert feed.status is SpotFeedStatus.ACTIVE
    assert feed.usage == 5
    assert feed.days_range == 7
    assert feed.detailed_message_shown is True
    assert feed.type is SpotFeedType.SHARED_PAGE
    assert "DEVICE1" in feed.devices
    assert len(feed.devices["DEVICE1"]) == 1
    assert feed.devices["DEVICE1"][0].id == 321


def test_spot_feed_from_json_handles_single_message_mapping():
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "messages": {
                    "message": {
                        "first": {
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "messageType": "TRACK",
                            "unixTime": "1689347405",
                        }
                    }
                },
            }
        }
    }

    feed.from_json(response)

    assert "DEVICE1" in feed.devices
    assert len(feed.devices["DEVICE1"]) == 1


def test_spot_feed_from_json_logs_unexpected_message_payload_type(caplog):
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "messages": {"message": "bogus"},
            }
        }
    }

    with caplog.at_level(logging.WARNING):
        feed.from_json(response)

    assert "Unexpected message payload type" in caplog.text
    assert feed.devices == {}


def test_spot_feed_from_json_skips_non_mapping_messages(caplog):
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "messages": {
                    "message": [
                        {
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "messageType": "TRACK",
                            "unixTime": "1689347405",
                        },
                        "bogus",
                    ]
                },
            }
        }
    }

    with caplog.at_level(logging.WARNING):
        feed.from_json(response)

    assert "Skipping non-mapping message payload" in caplog.text
    assert list(feed.devices) == ["DEVICE1"]
    assert len(feed.devices["DEVICE1"]) == 1


def test_spot_feed_from_json_normalizes_detailed_message_shown_flag():
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {
                    "detailedMessageShown": "false",
                },
                "messages": {"message": []},
            }
        }
    }

    feed.from_json(response)

    assert feed.detailed_message_shown is False


def test_spot_feed_from_json_uses_unix_time_when_datetime_missing():
    feed = SpotFeed(id="feed123", password="secret")
    response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347405",
                            "id": "321",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347405",
                            "messageType": "TRACK",
                            "latitude": "34.05",
                            "longitude": "-118.25",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }

    feed.from_json(response)

    assert "DEVICE1" in feed.devices
    assert len(feed.devices["DEVICE1"]) == 1
    message = feed.devices["DEVICE1"][0]
    assert message.date_time == datetime.datetime.fromtimestamp(1689347405, tz=UTC)


def test_spot_feed_from_json_merge_preserves_existing_messages():
    feed = SpotFeed(id="feed123", password="secret")
    first_response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347405",
                            "id": "321",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347405",
                            "messageType": "TRACK",
                            "latitude": "34.05",
                            "longitude": "-118.25",
                            "dateTime": "2023-07-14T16:30:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }
    second_response = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347406",
                            "id": "322",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347406",
                            "messageType": "TRACK",
                            "latitude": "34.06",
                            "longitude": "-118.26",
                            "dateTime": "2023-07-14T16:31:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }

    feed.from_json(first_response)
    feed.from_json(second_response, merge=True)

    assert "DEVICE1" in feed.devices
    assert [message.id for message in feed.devices["DEVICE1"]] == [322, 321]

    # Duplicated messages should be ignored when merging.
    feed.from_json(second_response, merge=True)
    assert [message.id for message in feed.devices["DEVICE1"]] == [322, 321]


def test_iter_messages_orders_messages_across_devices():
    feed = SpotFeed(id="feed123", password="")
    older = SpotMessage(id=1, date_time=datetime.datetime(2023, 1, 1, tzinfo=UTC))
    newer = SpotMessage(id=2, date_time=datetime.datetime(2023, 1, 2, tzinfo=UTC))
    newest = SpotMessage(id=3, date_time=datetime.datetime(2023, 1, 3, tzinfo=UTC))

    feed._add_message("device-a", newer)
    feed._add_message("device-a", older)
    feed._add_message("device-b", newest)

    ordered = list(feed.iter_messages())
    assert [message.id for message in ordered] == [3, 2, 1]

    ascending = list(feed.iter_messages(newest_first=False))
    assert [message.id for message in ascending] == [1, 2, 3]


def test_iter_messages_by_type_filters_results():
    feed = SpotFeed(id="feed123", password="")
    track_message = SpotMessage(
        id=1,
        date_time=datetime.datetime(2023, 1, 1, tzinfo=UTC),
        message_type=SpotMessageType.TRACK,
    )
    custom_message = SpotMessage(
        id=2,
        date_time=datetime.datetime(2023, 1, 2, tzinfo=UTC),
        message_type=SpotMessageType.CUSTOM,
    )
    feed._add_message("device-a", track_message)
    feed._add_message("device-b", custom_message)

    filtered = list(feed.iter_messages_by_type(SpotMessageType.CUSTOM))
    assert filtered == [custom_message]


def test_spot_feed_from_json_handles_missing_response(caplog):
    feed = SpotFeed(id="feed123", password="secret")

    with caplog.at_level(logging.WARNING):
        feed.from_json({})

    assert "No response payload" in caplog.text


def test_spot_feed_tracks_dropped_messages(caplog):
    feed = SpotFeed(id="feed123", password="secret")
    message = SpotMessage(id=1, messenger_id="device", unix_time=0, date_time=None)

    with caplog.at_level(logging.WARNING):
        feed._add_message("device", message)

    assert feed.dropped_message_count == 1
    assert "missing timestamp" in caplog.text
    assert "device" not in feed.devices


def test_format_request_datetime_requires_timezone():
    naive_dt = datetime.datetime(2023, 7, 14, 16, 30, 5)
    aware_dt = datetime.datetime(2023, 7, 14, 16, 30, 5, tzinfo=UTC)

    with pytest.raises(ValueError):
        SpotApi._format_request_datetime(naive_dt)

    assert SpotApi._format_request_datetime(aware_dt).endswith("+0000")


def test_request_wait_remaining_respects_configured_wait():
    api = SpotApi([("feed123", None)], api_wait_time=10)
    feed = api.get_feed()
    baseline = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)
    api._last_request[feed.id] = baseline
    api._now = lambda: baseline + datetime.timedelta(seconds=3)

    assert api._request_wait_remaining(feed) == pytest.approx(7.0)

    api._now = lambda: baseline + datetime.timedelta(seconds=30)
    assert api._request_wait_remaining(feed) == 0.0


def test_inter_feed_wait_remaining_only_blocks_other_feeds():
    api = SpotApi([("feed1", None), ("feed2", None)], feed_wait_time=5)
    feed1 = api.get_feed("feed1")
    feed2 = api.get_feed("feed2")
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._last_feed_request_id = "feed1"
    api._last_feed_request_time = baseline
    api._now = lambda: baseline + datetime.timedelta(seconds=1)

    assert api._inter_feed_wait_remaining(feed1) == 0.0
    remaining = api._inter_feed_wait_remaining(feed2)
    assert remaining == pytest.approx(4.0)

    api._now = lambda: baseline + datetime.timedelta(seconds=10)
    assert api._inter_feed_wait_remaining(feed2) == 0.0


def test_can_dispatch_request_combines_waits():
    api = SpotApi([("feed", None)], api_wait_time=12, feed_wait_time=6)
    feed = api.get_feed()
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._last_request[feed.id] = baseline
    api._last_feed_request_time = baseline
    api._last_feed_request_id = "other"
    api._now = lambda: baseline

    allowed, wait_seconds = api._can_dispatch_request(feed)
    assert not allowed
    assert wait_seconds == pytest.approx(6.0)

    api._now = lambda: baseline + datetime.timedelta(seconds=6)
    allowed, wait_seconds = api._can_dispatch_request(feed)
    assert not allowed
    assert wait_seconds == pytest.approx(6.0)

    api._now = lambda: baseline + datetime.timedelta(seconds=13)
    allowed, wait_seconds = api._can_dispatch_request(feed)
    assert allowed
    assert wait_seconds == 0.0


def test_retry_after_seconds_respects_numeric_header():
    api = SpotApi([("feed", None)], api_wait_time=99)
    response = httpx.Response(429, headers={"Retry-After": "42"})

    assert api._retry_after_seconds(response) == pytest.approx(42.0)


def test_retry_after_seconds_parses_http_date_header():
    baseline = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
    retry_time = baseline + datetime.timedelta(seconds=30)
    api = SpotApi([("feed", None)])
    api._now = lambda: baseline
    header_value = retry_time.strftime("%a, %d %b %Y %H:%M:%S GMT")
    response = httpx.Response(429, headers={"Retry-After": header_value})

    assert api._retry_after_seconds(response) == pytest.approx(30.0)


def test_retry_after_seconds_falls_back_to_default(caplog):
    api = SpotApi([("feed", None)], api_wait_time=12)
    response = httpx.Response(429, headers={"Retry-After": "not-a-date"})

    with caplog.at_level(logging.WARNING):
        wait = api._retry_after_seconds(response)

    assert wait == pytest.approx(12.0)
    assert "Retry-After" in caplog.text


def test_build_request_rejects_partial_date_ranges():
    api = SpotApi([("feed", None)])
    feed = api.get_feed()
    start = datetime.datetime(2023, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError):
        api._build_request(feed, start_dt=start, end_dt=None)


class _DummyHttpResponse:
    def __init__(self, payload, *, status_code=200, headers=None, text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload) if text is None else text

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _DummyHttpResponseRaises(_DummyHttpResponse):
    def __init__(self, text="not-json", *, status_code=200, headers=None):
        super().__init__({}, status_code=status_code, headers=headers, text=text)

    def json(self):  # pragma: no cover - exercised via SpotApi
        raise ValueError("boom")


class _DummyHttpClient:
    def __init__(self, response):
        self._response = response
        self.closed = False
        self.request_history = []

    async def get(self, url, params=None, headers=None):
        self.request_history.append((url, params, headers))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def aclose(self):
        self.closed = True


class _SequencedHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.closed = False
        self.request_history = []

    async def get(self, url, params=None, headers=None):
        self.request_history.append((url, params, headers))
        if not self._responses:
            raise RuntimeError("No responses remaining in sequenced client")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self):
        self.closed = True


def test_spot_api_rejects_multiple_client_sources():
    client = _DummyHttpClient(_DummyHttpResponse({"response": {}}))

    with pytest.raises(ValueError):
        SpotApi([("feed", None)], client=client, client_factory=lambda: client)


def test_ensure_client_validates_factory_output():
    api = SpotApi([("feed", None)], client_factory=lambda: object())

    with pytest.raises(TypeError):
        api._ensure_client()


def test_spot_api_closes_owned_client_after_request_and_context(monkeypatch):
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    created_clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    class TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", httpx.MockTransport(handler))
            super().__init__(*args, **kwargs)
            self.close_calls = 0
            created_clients.append(self)

        async def aclose(self) -> None:  # type: ignore[override]
            self.close_calls += 1
            await super().aclose()

    monkeypatch.setattr(spot_api.client.httpx, "AsyncClient", TrackingAsyncClient)

    async def exercise_request() -> TrackingAsyncClient:
        api = SpotApi([("feed", None)])
        result = await api.request()
        assert result.status is SpotRequestStatus.SUCCESS
        client = created_clients[-1]
        assert isinstance(client, TrackingAsyncClient)
        assert client.close_calls == 0
        assert not client.is_closed
        await api.aclose()
        assert client.close_calls == 1
        assert client.is_closed
        return client

    first_client = asyncio.run(exercise_request())

    async def exercise_context() -> TrackingAsyncClient:
        async with SpotApi([("feed", None)]) as api:
            client = api._client
            assert isinstance(client, TrackingAsyncClient)
            assert not client.is_closed
        assert client is not None
        assert client.is_closed
        assert client.close_calls == 1
        return client  # type: ignore[return-value]

    second_client = asyncio.run(exercise_context())

    assert first_client is not second_client


def test_close_disposes_owned_client(monkeypatch):
    created_clients: list[httpx.AsyncClient] = []

    class TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault(
                "transport", httpx.MockTransport(lambda request: httpx.Response(200))
            )
            super().__init__(*args, **kwargs)
            self.close_calls = 0
            created_clients.append(self)

        async def aclose(self) -> None:  # type: ignore[override]
            self.close_calls += 1
            await super().aclose()

    monkeypatch.setattr(spot_api.client.httpx, "AsyncClient", TrackingAsyncClient)

    api = SpotApi([("feed", None)])
    client = api._ensure_client()

    assert isinstance(client, TrackingAsyncClient)
    assert client.close_calls == 0
    assert not client.is_closed

    api.close()

    assert client.is_closed
    assert client.close_calls == 1
    assert api._client is None


def test_sync_context_manager_closes_client(monkeypatch):
    created_clients: list[httpx.AsyncClient] = []

    class TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault(
                "transport", httpx.MockTransport(lambda request: httpx.Response(200))
            )
            super().__init__(*args, **kwargs)
            self.close_calls = 0
            created_clients.append(self)

        async def aclose(self) -> None:  # type: ignore[override]
            self.close_calls += 1
            await super().aclose()

    monkeypatch.setattr(spot_api.client.httpx, "AsyncClient", TrackingAsyncClient)

    with SpotApi([("feed", None)]) as api:
        client = api._client
        assert isinstance(client, TrackingAsyncClient)
        assert not client.is_closed

    assert client is not None
    assert client.is_closed
    assert client.close_calls == 1
    assert created_clients


def test_client_factory_creates_and_closes_client():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    factory_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    class FactoryClient(httpx.AsyncClient):
        def __init__(self) -> None:
            super().__init__(transport=httpx.MockTransport(handler))
            self.close_calls = 0

        async def aclose(self) -> None:  # type: ignore[override]
            self.close_calls += 1
            await super().aclose()

    def factory() -> httpx.AsyncClient:
        factory_calls["count"] += 1
        return FactoryClient()

    api = SpotApi([("feed", None)], client_factory=factory)
    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.SUCCESS
    assert factory_calls["count"] == 1
    client = api._client
    assert isinstance(client, FactoryClient)
    assert client.close_calls == 0

    asyncio.run(api.aclose())

    assert client.close_calls == 1
    assert client.is_closed


def test_request_returns_throttled_result():
    api = SpotApi([("feed", None)], api_wait_time=10)
    feed = api.get_feed()
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._last_request[feed.id] = baseline
    api._now = lambda: baseline

    result = asyncio.run(api.request())

    assert isinstance(result, SpotRequestResult)
    assert result.status is SpotRequestStatus.THROTTLED
    assert result.wait_seconds == pytest.approx(10.0)
    assert not result.succeeded
    assert result.request_url is None
    assert result.request_params is None


def test_request_success_returns_enriched_result():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    headers = {"x-test": "1"}
    response = _DummyHttpResponse(payload, headers=headers)
    client = _DummyHttpClient(response)
    api = SpotApi([("feed", None)], client=client)
    api._now = lambda: datetime.datetime(2023, 1, 1, tzinfo=UTC)

    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.SUCCESS
    assert result.response == payload
    assert result.feed is api.get_feed()
    assert result.request_time.tzinfo is UTC
    assert result.succeeded
    assert client.request_history
    request_url, params, sent_headers = client.request_history[0]
    assert result.status_code == 200
    assert result.response_headers == headers
    assert result.response_text == response.text
    assert result.request_url == request_url
    assert result.request_params == params
    assert result.request_headers == sent_headers
    assert sent_headers is None
    assert params["pageSize"] == str(api.DEFAULT_PAGE_SIZE)


def test_request_merges_default_headers_and_extra_params():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi(
        [("feed", "secret")],
        client=client,
        default_request_headers={"User-Agent": "spot-client"},
        default_query_params={"custom": "1", "feedPassword": "ignored"},
    )

    result = asyncio.run(
        api.request(
            page=2,
            page_size=5,
            extra_params={"custom": "override", "extra": "value"},
            headers={"X-Trace": "abc123"},
        )
    )

    assert result.status is SpotRequestStatus.SUCCESS
    url, params, sent_headers = client.request_history[0]
    assert url.endswith("/message.json")
    assert params["pageSize"] == "5"
    assert params["start"] == "6"
    assert params["custom"] == "override"
    assert params["extra"] == "value"
    assert params["feedPassword"] == "secret"
    assert sent_headers == {
        "User-Agent": "spot-client",
        "X-Trace": "abc123",
    }
    assert result.request_headers == sent_headers


def test_request_applies_custom_page_size():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi([("feed", None)], client=client)

    asyncio.run(api.request(page=3, page_size=10))

    params = client.request_history[0][1]
    assert params["start"] == "21"
    assert params["pageSize"] == "10"


def test_request_latest_ignores_page_size_in_payload():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi([("feed", None)], client=client)

    result = asyncio.run(api.request_latest(page_size=25))

    url, params, sent_headers = client.request_history[0]
    assert url.endswith("/latest.json")
    assert params == {}
    assert sent_headers is None
    assert result.request_url.endswith("/latest.json")
    assert result.request_params == {}


def test_request_sync_executes_request_without_event_loop():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    api = SpotApi(
        [("feed", None)], client=_DummyHttpClient(_DummyHttpResponse(payload))
    )

    result = api.request_sync()

    assert result.status is SpotRequestStatus.SUCCESS


def test_request_sync_handles_running_event_loop_via_executor():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    api = SpotApi(
        [("feed", None)], client=_DummyHttpClient(_DummyHttpResponse(payload))
    )

    async def invoke_sync_request():
        result = api.request_sync()
        assert result.status is SpotRequestStatus.SUCCESS

    asyncio.run(invoke_sync_request())


def test_request_with_dates_sync_returns_metadata():
    payload = {
        "response": {"feedMessageResponse": {"feed": {}, "messages": {"message": []}}}
    }
    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi([("feed", None)], client=client)
    start = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    end = datetime.datetime(2023, 1, 2, tzinfo=UTC)

    result = api.request_with_dates_sync(start, end)

    assert result.request_params["startDate"].startswith("2023-01-01")
    assert result.request_params["endDate"].startswith("2023-01-02")
    assert result.request_params["pageSize"] == str(api.DEFAULT_PAGE_SIZE)


def test_request_rejects_invalid_page_size():
    client = _DummyHttpClient(_DummyHttpResponse({"response": {}}))
    api = SpotApi([("feed", None)], client=client)

    with pytest.raises(ValueError):
        asyncio.run(api.request(page_size=0))

    assert client.request_history == []


def test_request_merge_accumulates_messages_across_pages():
    page_one = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "1",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347405",
                            "id": "321",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347405",
                            "messageType": "TRACK",
                            "latitude": "34.05",
                            "longitude": "-118.25",
                            "dateTime": "2023-07-14T16:30:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }
    page_two = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "2",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347406",
                            "id": "322",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347406",
                            "messageType": "TRACK",
                            "latitude": "34.06",
                            "longitude": "-118.26",
                            "dateTime": "2023-07-14T16:31:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }

    client = _SequencedHttpClient(
        [
            _DummyHttpResponse(page_one),
            _DummyHttpResponse(page_two),
            _DummyHttpResponse(page_two),
        ]
    )
    api = SpotApi([("feed", None)], client=client)
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._now = lambda: baseline

    first_result = asyncio.run(api.request(page=1))
    assert first_result.status is SpotRequestStatus.SUCCESS

    api._now = lambda: baseline + datetime.timedelta(
        seconds=SpotApi.SPOT_API_WAIT_TIME + 1
    )
    second_result = asyncio.run(api.request(page=2, merge=True))
    assert second_result.status is SpotRequestStatus.SUCCESS

    feed = api.get_feed()
    assert [message.id for message in feed.devices["DEVICE1"]] == [322, 321]

    api._now = lambda: baseline + datetime.timedelta(
        seconds=2 * (SpotApi.SPOT_API_WAIT_TIME + 1)
    )
    third_result = asyncio.run(api.request(page=2, merge=True))
    assert third_result.status is SpotRequestStatus.SUCCESS
    assert [message.id for message in feed.devices["DEVICE1"]] == [322, 321]


def test_request_all_pages_fetches_sequential_pages():
    page_one = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "1",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347405",
                            "id": "321",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347405",
                            "messageType": "TRACK",
                            "latitude": "34.05",
                            "longitude": "-118.25",
                            "dateTime": "2023-07-14T16:30:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }
    page_two = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "2",
                "messages": {
                    "message": [
                        {
                            "@clientUnixTime": "1689347406",
                            "id": "322",
                            "messengerId": "DEVICE1",
                            "messengerName": "Device",
                            "unixTime": "1689347406",
                            "messageType": "TRACK",
                            "latitude": "34.06",
                            "longitude": "-118.26",
                            "dateTime": "2023-07-14T16:31:05+0000",
                            "batteryState": "GOOD",
                        }
                    ]
                },
            }
        }
    }

    client = _SequencedHttpClient(
        [_DummyHttpResponse(page_one), _DummyHttpResponse(page_two)]
    )
    api = SpotApi([("feed", None)], client=client)

    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    call_count = {"value": 0}

    def advancing_now():
        current = baseline + datetime.timedelta(
            seconds=call_count["value"] * (SpotApi.SPOT_API_WAIT_TIME + 1)
        )
        call_count["value"] += 1
        return current

    api._now = advancing_now

    async def gather_results():
        results = []
        async for result in api.request_all_pages():
            results.append(result)
        return results

    results = asyncio.run(gather_results())

    assert [result.status for result in results] == [SpotRequestStatus.SUCCESS] * 2
    feed = api.get_feed()
    assert [message.id for message in feed.devices["DEVICE1"]] == [322, 321]

    assert len(client.request_history) == 2
    assert client.request_history[0][1]["pageSize"] == str(api.DEFAULT_PAGE_SIZE)
    assert client.request_history[1][1]["start"] == "51"


def test_request_all_pages_respects_custom_page_size():
    page_one = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "1",
                "messages": {"message": []},
            }
        }
    }
    page_two = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "1",
                "totalCount": "2",
                "start": "2",
                "messages": {"message": []},
            }
        }
    }

    client = _SequencedHttpClient(
        [_DummyHttpResponse(page_one), _DummyHttpResponse(page_two)]
    )
    api = SpotApi([("feed", None)], client=client)

    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    call_count = {"value": 0}

    def advancing_now():
        current = baseline + datetime.timedelta(
            seconds=call_count["value"] * (SpotApi.SPOT_API_WAIT_TIME + 1)
        )
        call_count["value"] += 1
        return current

    api._now = advancing_now

    async def gather_results():
        results = []
        async for result in api.request_all_pages(page_size=10):
            results.append(result)
        return results

    results = asyncio.run(gather_results())

    assert [result.status for result in results] == [SpotRequestStatus.SUCCESS] * 2
    assert client.request_history[0][1]["pageSize"] == "10"
    assert client.request_history[1][1]["start"] == "11"


def test_request_all_pages_handles_non_numeric_counts():
    payload = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "not-a-number",
                "totalCount": "",
                "start": None,
                "messages": {"message": []},
            }
        }
    }

    client = _DummyHttpClient(_DummyHttpResponse(payload))
    api = SpotApi([("feed", None)], client=client)

    async def gather_results():
        results = []
        async for result in api.request_all_pages():
            results.append(result)
        return results

    results = asyncio.run(gather_results())

    assert [result.status for result in results] == [SpotRequestStatus.SUCCESS]
    assert len(client.request_history) == 1


def test_request_all_pages_honors_throttle_budget():
    api = SpotApi([("feed", None)])
    feed = api.get_feed()

    throttled_result = SpotRequestResult(
        SpotRequestStatus.THROTTLED, feed, wait_seconds=0.0
    )
    success_payload = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "0",
                "totalCount": "0",
                "start": "1",
                "messages": {"message": []},
            }
        }
    }
    success_result = SpotRequestResult(
        SpotRequestStatus.SUCCESS,
        feed,
        response=success_payload,
    )

    responses = [throttled_result, throttled_result, throttled_result, success_result]

    async def fake_request(self, *args, **kwargs):
        return responses.pop(0)

    api._request = types.MethodType(fake_request, api)

    async def gather_results():
        collected = []
        async for outcome in api.request_all_pages(max_throttled_retries=2):
            collected.append(outcome)
        return collected

    results = asyncio.run(gather_results())

    assert len(results) == 3
    assert all(result.status is SpotRequestStatus.THROTTLED for result in results)
    assert responses == [success_result]


def test_request_all_pages_applies_exponential_backoff(monkeypatch):
    api = SpotApi([("feed", None)])
    feed = api.get_feed()

    throttled = SpotRequestResult(SpotRequestStatus.THROTTLED, feed, wait_seconds=None)
    success_payload = {
        "response": {
            "feedMessageResponse": {
                "feed": {},
                "count": "0",
                "totalCount": "0",
                "start": "1",
                "messages": {"message": []},
            }
        }
    }
    success = SpotRequestResult(
        SpotRequestStatus.SUCCESS,
        feed,
        response=success_payload,
    )

    responses = iter([throttled, throttled, throttled, success])

    async def fake_request(self, *args, **kwargs):
        return next(responses)

    api._request = types.MethodType(fake_request, api)

    observed_waits: list[float] = []

    async def fake_sleep(duration):
        observed_waits.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def collect():
        collected = []
        async for outcome in api.request_all_pages():
            collected.append(outcome)
        return collected

    results = asyncio.run(collect())

    assert [result.status for result in results[:-1]] == [
        SpotRequestStatus.THROTTLED
    ] * 3
    assert results[-1].status is SpotRequestStatus.SUCCESS
    assert observed_waits == pytest.approx([2.0, 4.0, 8.0])


def test_request_reports_decode_errors():
    client = _DummyHttpClient(_DummyHttpResponseRaises())
    api = SpotApi([("feed", None)], client=client)
    api._now = lambda: datetime.datetime(2023, 1, 1, tzinfo=UTC)

    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.DECODE_ERROR
    assert isinstance(result.error, ValueError)
    assert result.request_time is not None
    assert result.status_code == 200
    assert result.response_headers == {}
    assert result.response_text == "not-json"
    assert result.request_headers is None


def test_request_reports_transport_errors():
    transport_error = httpx.ConnectError("boom")
    client = _DummyHttpClient(transport_error)
    api = SpotApi([("feed", None)], client=client)
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._now = lambda: baseline

    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.TRANSPORT_ERROR
    assert result.error is transport_error
    assert result.request_time == baseline
    assert result.status_code is None
    assert result.response_headers is None
    assert result.response_text is None
    assert result.request_headers is None
    feed = api.get_feed()
    assert api._last_request[feed.id] == baseline
    assert api._last_feed_request_time == baseline
    assert api._last_feed_request_id == feed.id


def test_request_treats_http_429_as_throttled():
    request = httpx.Request("GET", "https://example.test/feed/message.json")
    response = httpx.Response(
        429,
        request=request,
        text="Too Many Requests",
        headers={"Retry-After": "120"},
    )
    transport_error = httpx.HTTPStatusError(
        "too many", request=request, response=response
    )
    client = _DummyHttpClient(transport_error)
    api = SpotApi([("feed", None)], client=client)
    baseline = datetime.datetime(2023, 1, 1, tzinfo=UTC)
    api._now = lambda: baseline

    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.THROTTLED
    assert result.wait_seconds == pytest.approx(120.0)
    assert result.error is None
    assert result.status_code == 429
    assert result.response_headers is not None
    assert result.response_headers.get("retry-after") == "120"
    assert result.response_text == "Too Many Requests"
    assert result.request_headers is None


def test_request_includes_response_details_for_http_status_error():
    request = httpx.Request("GET", "https://example.test/feed/message.json")
    response = httpx.Response(
        503, request=request, text="Service unavailable", headers={"X-Test": "1"}
    )
    transport_error = httpx.HTTPStatusError("boom", request=request, response=response)
    client = _DummyHttpClient(transport_error)
    api = SpotApi([("feed", None)], client=client)
    api._now = lambda: datetime.datetime(2023, 1, 1, tzinfo=UTC)

    result = asyncio.run(api.request())

    assert result.status is SpotRequestStatus.TRANSPORT_ERROR
    assert result.status_code == 503
    assert result.response_text == "Service unavailable"
    assert result.response_headers is not None
    assert result.response_headers.get("x-test") == "1"
    assert result.request_headers is None


def test_aclose_skips_external_client_shutdown():
    client = _DummyHttpClient(_DummyHttpResponse({"response": {}}))
    api = SpotApi([("feed", None)], client=client)

    asyncio.run(api.aclose())

    assert client.closed is False
