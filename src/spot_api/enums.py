"""Enumeration definitions for the Spot API client."""

from __future__ import annotations

import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class SpotRequestType(Enum):
    """Represents the type of request that can be made to the Spot API."""

    MESSAGE = 0
    LATEST = auto()


class SpotBatteryState(Enum):
    """Represents the state of a Spot device battery."""

    GOOD = 0
    LOW = auto()
    CRITICAL = auto()
    CHARGING = auto()
    REPLACE = auto()
    UNKNOWN_STATE = auto()

    @staticmethod
    def from_str(batt_state: str):
        """Create a :class:`SpotBatteryState` from a raw string value."""

        if not batt_state:
            logger.debug("Received empty battery state value.")
            return SpotBatteryState.UNKNOWN_STATE

        normalized = batt_state.lower()

        match normalized:
            case "good":
                return SpotBatteryState.GOOD
            case "low":
                return SpotBatteryState.LOW
            case "critical":
                return SpotBatteryState.CRITICAL
            case "charging":
                return SpotBatteryState.CHARGING
            case "replace" | "needs replacing" | "needsreplacing":
                return SpotBatteryState.REPLACE
            case _:
                logger.warning("Unrecognized battery state: %s", batt_state)
                return SpotBatteryState.UNKNOWN_STATE

    def __str__(self) -> str:
        match self:
            case SpotBatteryState.GOOD:
                return "Good"
            case SpotBatteryState.LOW:
                return "Low"
            case SpotBatteryState.CRITICAL:
                return "Critical"
            case SpotBatteryState.CHARGING:
                return "Charging"
            case SpotBatteryState.REPLACE:
                return "Replace"
            case _:
                return "Unknown Battery State"


class SpotDeviceType(Enum):
    """Represents the type of Spot device that produced a message."""

    SPOT_TRACE = 0
    SPOT_GEN3 = auto()
    SPOT_GEN4 = auto()
    SPOT_X = auto()
    UNKNOWN_DEVICE = auto()

    @staticmethod
    def from_str(dev_type: str):
        """Create a :class:`SpotDeviceType` from a raw string value."""

        if not dev_type:
            logger.debug("Received empty device type value.")
            return SpotDeviceType.UNKNOWN_DEVICE

        normalized = dev_type.replace("_", " ").replace("-", " ").strip().upper()

        match normalized:
            case "SPOTTRACE" | "SPOT TRACE":
                return SpotDeviceType.SPOT_TRACE
            case "SPOT GEN3" | "SPOTGEN3" | "GEN3":
                return SpotDeviceType.SPOT_GEN3
            case "SPOT GEN4" | "SPOTGEN4" | "GEN4":
                return SpotDeviceType.SPOT_GEN4
            case "SPOT X" | "SPOTX":
                return SpotDeviceType.SPOT_X
            case _:
                logger.warning("Unrecognized device type: %s", dev_type)
                return SpotDeviceType.UNKNOWN_DEVICE

    def __str__(self) -> str:
        match self:
            case SpotDeviceType.SPOT_TRACE:
                return "Spot Trace"
            case SpotDeviceType.SPOT_GEN3:
                return "SPOT Gen3"
            case SpotDeviceType.SPOT_GEN4:
                return "SPOT Gen4"
            case SpotDeviceType.SPOT_X:
                return "SPOT X"
            case _:
                return "Unknown Device"


class SpotFeedType(Enum):
    """Represents the type of a Spot feed."""

    SHARED_PAGE = 0
    PRIVATE_PAGE = auto()
    ADVENTURE = auto()
    ENTERPRISE_ACCOUNT = auto()
    UNKNOWN_TYPE = auto()

    @staticmethod
    def from_str(feed_type: str):
        """Create a :class:`SpotFeedType` from a raw string value."""

        if not feed_type:
            logger.debug("Received empty feed type value.")
            return SpotFeedType.UNKNOWN_TYPE

        normalized = feed_type.lower().replace("_", " ").strip()

        match normalized:
            case "shared page":
                return SpotFeedType.SHARED_PAGE
            case "private page":
                return SpotFeedType.PRIVATE_PAGE
            case "adventure":
                return SpotFeedType.ADVENTURE
            case "enterprise account" | "enterprise":
                return SpotFeedType.ENTERPRISE_ACCOUNT
            case _:
                logger.warning("Unrecognized feed type: %s", feed_type)
                return SpotFeedType.UNKNOWN_TYPE

    def __str__(self) -> str:
        match self:
            case SpotFeedType.SHARED_PAGE:
                return "Shared Page"
            case SpotFeedType.PRIVATE_PAGE:
                return "Private Page"
            case SpotFeedType.ADVENTURE:
                return "Adventure"
            case SpotFeedType.ENTERPRISE_ACCOUNT:
                return "Enterprise Account"
            case _:
                return "Unknown Feed Type"


class SpotFeedStatus(Enum):
    """Represents the status of a Spot feed."""

    ACTIVE = 0
    INACTIVE = auto()
    UNKNOWN_STATUS = auto()

    @staticmethod
    def from_str(status: str):
        """Create a :class:`SpotFeedStatus` from a raw string value."""

        if not status:
            logger.debug("Received empty feed status value.")
            return SpotFeedStatus.UNKNOWN_STATUS

        match status.lower():
            case "active":
                return SpotFeedStatus.ACTIVE
            case "inactive":
                return SpotFeedStatus.INACTIVE
            case _:
                logger.warning("Unrecognized feed status: %s", status)
                return SpotFeedStatus.UNKNOWN_STATUS

    def __str__(self) -> str:
        match self:
            case SpotFeedStatus.ACTIVE:
                return "Active"
            case SpotFeedStatus.INACTIVE:
                return "Inactive"
            case _:
                return "Unknown Status"


class SpotMessageType(Enum):
    """Represents the message type of a Spot message."""

    OK = 0
    TRACK = auto()
    EXTREME_TRACK = auto()
    UNLIMITED_TRACK = auto()
    NEW_MOVEMENT = auto()
    HELP = auto()
    HELP_CANCEL = auto()
    CUSTOM = auto()
    POI = auto()
    STOP = auto()
    POWER_OFF = auto()
    UNKNOWN_TYPE = auto()

    @staticmethod
    def from_str(msg_type: str):
        """Create a :class:`SpotMessageType` from a raw string value."""

        if not msg_type:
            logger.debug("Received empty message type value.")
            return SpotMessageType.UNKNOWN_TYPE

        match msg_type.lower().replace("-", " "):
            case "ok":
                return SpotMessageType.OK
            case "track":
                return SpotMessageType.TRACK
            case "extreme track":
                return SpotMessageType.EXTREME_TRACK
            case "unlimited track":
                return SpotMessageType.UNLIMITED_TRACK
            case "newmovement" | "new movement":
                return SpotMessageType.NEW_MOVEMENT
            case "help":
                return SpotMessageType.HELP
            case "help cancel":
                return SpotMessageType.HELP_CANCEL
            case "custom":
                return SpotMessageType.CUSTOM
            case "poi":
                return SpotMessageType.POI
            case "stop":
                return SpotMessageType.STOP
            case "power off":
                return SpotMessageType.POWER_OFF
            case _:
                logger.warning("Unrecognized message type: %s", msg_type)
                return SpotMessageType.UNKNOWN_TYPE

    def __str__(self) -> str:
        match self:
            case SpotMessageType.OK:
                return "OK"
            case SpotMessageType.TRACK:
                return "Track"
            case SpotMessageType.EXTREME_TRACK:
                return "Extreme Track"
            case SpotMessageType.UNLIMITED_TRACK:
                return "Unlimited Track"
            case SpotMessageType.NEW_MOVEMENT:
                return "New Movement"
            case SpotMessageType.HELP:
                return "Help"
            case SpotMessageType.HELP_CANCEL:
                return "Help Cancel"
            case SpotMessageType.CUSTOM:
                return "Custom"
            case SpotMessageType.POI:
                return "POI"
            case SpotMessageType.STOP:
                return "Stop"
            case SpotMessageType.POWER_OFF:
                return "Power Off"
            case _:
                return "Unknown Type"


__all__ = [
    "SpotRequestType",
    "SpotBatteryState",
    "SpotDeviceType",
    "SpotFeedType",
    "SpotFeedStatus",
    "SpotMessageType",
]
