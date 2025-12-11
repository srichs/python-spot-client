"""Data models and parsing helpers for Spot API responses."""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .enums import (
    SpotBatteryState,
    SpotDeviceType,
    SpotFeedStatus,
    SpotFeedType,
    SpotMessageType,
)

logger = logging.getLogger(__name__)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"y", "yes", "true", "1"}:
            return True
        if normalized in {"n", "no", "false", "0"}:
            return False

    return bool(value)


def _coerce_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Unable to convert value '%s' to float", value)
        return None


def _coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Unable to convert value '%s' to int", value)
        return None


_OFFSET_SUFFIX_RE = re.compile(r"([+-]\d{2})(\d{2})$")


def _parse_datetime(raw_datetime: Optional[str]) -> Optional[datetime.datetime]:
    if not raw_datetime:
        return None

    value = raw_datetime.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    else:
        match = _OFFSET_SUFFIX_RE.search(value)
        if match:
            value = value[: match.start()] + f"{match.group(1)}:{match.group(2)}"

    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Unable to parse datetime value '%s'", raw_datetime)
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)

    return parsed.astimezone(datetime.timezone.utc)


@dataclass
class SpotMessage:
    """Represents a single message returned by the Spot API."""

    client_unix_time: str = ""
    id: Optional[int] = None
    messenger_id: str = ""
    messenger_name: str = ""
    unix_time: Optional[int] = None
    message_type: Optional[SpotMessageType] = None
    latitude: float = 0.0
    longitude: float = 0.0
    model_id: Optional[SpotDeviceType] = None
    show_custom_message: bool = False
    date_time: Optional[datetime.datetime] = None
    battery_state: Optional[SpotBatteryState] = None
    hidden: Optional[int] = None
    altitude: Optional[int] = None

    @classmethod
    def from_json(cls, message: Mapping[str, Any]) -> "SpotMessage":
        """Create a :class:`SpotMessage` from a findmespot API JSON message."""

        if not isinstance(message, Mapping):
            raise TypeError("message must be a mapping")

        required_fields = ["@clientUnixTime", "id", "messengerId", "messengerName", "unixTime"]
        missing_fields = [field for field in required_fields if field not in message]
        if missing_fields:
            logger.warning("Missing expected message fields: %s", ", ".join(missing_fields))

        message_type = None
        if "messageType" in message:
            raw_message_type = message.get("messageType")
            if raw_message_type is not None:
                message_type = SpotMessageType.from_str(str(raw_message_type))

        latitude = cls._check_latitude(_coerce_float(message.get("latitude")))
        longitude = cls._check_longitude(_coerce_float(message.get("longitude")))

        model_id = None
        if "modelId" in message:
            raw_model_id = message.get("modelId")
            if raw_model_id is not None:
                model_id = SpotDeviceType.from_str(str(raw_model_id))

        show_custom_message = message.get("showCustomMsg", "") == "Y"

        date_time = _parse_datetime(message.get("dateTime"))
        raw_battery_state = message.get("batteryState")
        battery_state = SpotBatteryState.from_str("" if raw_battery_state is None else str(raw_battery_state))

        hidden = _coerce_int(message.get("hidden", 0))
        altitude = _coerce_int(message.get("altitude", 0))

        return cls(
            client_unix_time=message.get("@clientUnixTime", ""),
            id=_coerce_int(message.get("id", 0)),
            messenger_id=message.get("messengerId", ""),
            messenger_name=message.get("messengerName", ""),
            unix_time=_coerce_int(message.get("unixTime", 0)),
            message_type=message_type,
            latitude=latitude,
            longitude=longitude,
            model_id=model_id,
            show_custom_message=show_custom_message,
            date_time=date_time,
            battery_state=battery_state,
            hidden=hidden,
            altitude=altitude,
        )

    def get_short_datetime(self) -> str:
        """Get a shortened form of the datetime of the message."""

        if self.date_time:
            return self.date_time.strftime("%Y-%m-%d %H:%M:%S")

        if self.unix_time:
            try:
                unix_time_int = int(self.unix_time)
            except (TypeError, ValueError):
                pass
            else:
                return datetime.datetime.fromtimestamp(
                    unix_time_int, tz=datetime.timezone.utc
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

        return ""

    def get_location(self) -> str:
        """Return the location information as a string."""

        return f"{self.latitude}, {self.longitude}, {self.altitude}"

    @staticmethod
    def _check_latitude(latitude: Optional[float]) -> float:
        if latitude is None or latitude < -90.0 or latitude > 90.0:
            return 0.0
        return latitude

    @staticmethod
    def _check_longitude(longitude: Optional[float]) -> float:
        if longitude is None or longitude < -180.0 or longitude > 180.0:
            return 0.0
        return longitude

    def __str__(self) -> str:
        msg_str = "-------------------------------\n"
        msg_str += f"Spot Message ({self.id})\n"
        msg_str += (
            f"'{self.messenger_name}' {self.messenger_id} ({self.model_id} - {self.message_type})\n"
        )
        msg_str += f"Battery: {self.battery_state}\n"
        timestamp = (
            self.date_time.isoformat(" ") if self.date_time is not None else self.get_short_datetime()
        )
        msg_str += f"{timestamp} ({self.unix_time})\n"
        msg_str += self.get_location()
        return msg_str


@dataclass
class SpotFeed:
    """Models a feed returned by the Spot API."""

    id: str
    password: str
    name: str = ""
    description: str = ""
    status: Optional[SpotFeedStatus] = None
    usage: Optional[int] = None
    days_range: Optional[int] = None
    detailed_message_shown: bool = False
    type: Optional[SpotFeedType] = None
    devices: Dict[str, List[SpotMessage]] = field(default_factory=dict)
    dropped_message_count: int = 0

    def from_json(self, response: Mapping[str, Any], *, merge: bool = False) -> None:
        """Populate the feed from a findmespot API JSON response."""

        if not isinstance(response, Mapping):
            raise TypeError("response must be a mapping")

        if "response" not in response:
            logger.warning("No response payload present in Spot feed data: %s", response)
            return

        if "feedMessageResponse" not in response["response"]:
            logger.warning("No feedMessageResponse present in Spot feed response: %s", response)
            return

        feed_message_response = response["response"]["feedMessageResponse"]
        if not isinstance(feed_message_response, Mapping):
            logger.warning(
                "feedMessageResponse payload was not a mapping in feed %s response", self.id
            )
            return
        feed_json = feed_message_response.get("feed", {})
        if not isinstance(feed_json, Mapping):
            feed_json = {}

        self.name = feed_json.get("name", "")
        self.description = feed_json.get("description", "")
        raw_status = feed_json.get("status")
        self.status = (
            SpotFeedStatus.from_str(str(raw_status))
            if raw_status is not None
            else None
        )
        self.usage = _coerce_int(feed_json.get("usage", 0))
        self.days_range = _coerce_int(feed_json.get("daysRange", 0))
        self.detailed_message_shown = _coerce_bool(
            feed_json.get("detailedMessageShown", False)
        )
        raw_type = feed_json.get("type")
        self.type = (
            SpotFeedType.from_str(str(raw_type))
            if raw_type is not None
            else None
        )
        count = _coerce_int(feed_message_response.get("count", 0))

        if not merge:
            self.devices.clear()
            self.dropped_message_count = 0

        logger.debug(
            "Parsed feed metadata for %s (count=%s, status=%s)",
            self.id,
            count,
            self.status,
        )

        messages = feed_message_response.get("messages", {})
        message_payload: Any
        if isinstance(messages, Mapping):
            message_payload = messages.get("message")
        else:
            message_payload = messages

        if not message_payload:
            logger.info("No messages present in feed %s response", self.id)
            return

        iterable: Iterable
        if isinstance(message_payload, Mapping):
            iterable = message_payload.values()
        elif isinstance(message_payload, Sequence) and not isinstance(message_payload, (str, bytes)):
            iterable = message_payload
        else:
            logger.warning(
                "Unexpected message payload type %s in feed %s response",
                type(message_payload).__name__,
                self.id,
            )
            return

        for message_json in iterable:
            if not isinstance(message_json, Mapping):
                logger.warning(
                    "Skipping non-mapping message payload for feed %s: %s",
                    self.id,
                    message_json,
                )
                continue
            msg_id = message_json.get("messengerId")
            if not msg_id:
                logger.warning("Encountered message without messengerId in feed %s", self.id)
                continue

            message = SpotMessage.from_json(message_json)
            self._add_message(msg_id, message)

    def get_latest_messages(self) -> list[SpotMessage]:
        """Return the latest message for each device in the feed."""

        messages: List[SpotMessage] = []

        for device in self.devices.values():
            if device:
                messages.append(device[0])
        return messages

    def iter_messages(self, *, newest_first: bool = True) -> Iterable[SpotMessage]:
        """Yield messages across all devices ordered by timestamp."""

        all_messages: List[SpotMessage] = []
        for device_messages in self.devices.values():
            all_messages.extend(device_messages)

        all_messages.sort(
            key=lambda message: message.date_time or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
            reverse=newest_first,
        )

        for message in all_messages:
            yield message

    def iter_messages_by_type(
        self, message_type: SpotMessageType, *, newest_first: bool = True
    ) -> Iterable[SpotMessage]:
        """Yield messages filtered by :class:`SpotMessageType`."""

        for message in self.iter_messages(newest_first=newest_first):
            if message.message_type is message_type:
                yield message

    def _add_message(self, messenger_id: str, message: SpotMessage) -> None:
        message_datetime = message.date_time

        if message_datetime is None and message.unix_time:
            try:
                unix_seconds = int(message.unix_time)
            except (TypeError, ValueError):
                unix_seconds = 0

            if unix_seconds > 0:
                try:
                    message_datetime = datetime.datetime.fromtimestamp(
                        unix_seconds, tz=datetime.timezone.utc
                    )
                except (OverflowError, OSError, ValueError):
                    message_datetime = None
                else:
                    message.date_time = message_datetime

        if message_datetime is None:
            self.dropped_message_count += 1
            logger.warning(
                "Skipping message %s for messenger %s in feed %s due to missing timestamp",
                message.id,
                messenger_id,
                self.id,
            )
            return

        device_messages = self.devices.setdefault(messenger_id, [])

        if any(existing.id == message.id for existing in device_messages):
            logger.debug(
                "Skipping duplicate message %s for messenger %s in feed %s",
                message.id,
                messenger_id,
                self.id,
            )
            return

        insert_index = len(device_messages)
        for idx, existing in enumerate(device_messages):
            existing_dt = existing.date_time
            if existing_dt is None or existing_dt <= message_datetime:
                insert_index = idx
                break

        device_messages.insert(insert_index, message)
        logger.debug(
            "Added message %s for messenger %s to feed %s",
            message.id,
            messenger_id,
            self.id,
        )

    def __str__(self) -> str:
        if self.name == "" and self.status is None:
            return "No feed data."
        msg_str = "-------------------------------\n"
        msg_str += f"Feed - {self.id}\n"
        msg_str += f"'{self.name}' {self.status} - {self.type}\n"
        msg_str += f"Usage: {self.usage}, Days Range: {self.days_range}\n"

        if len(self.devices) > 0:
            msg_str += "\nDevices: \n"

            for key in self.devices.keys():
                msg_str += f"  {key}\n"

            msg_str += "\n"

            for device in self.devices.values():
                for message in device:
                    if message is not None:
                        msg_str += f"{message}\n"
        return msg_str


__all__ = [
    "_coerce_float",
    "_coerce_int",
    "_parse_datetime",
    "SpotFeed",
    "SpotMessage",
]
