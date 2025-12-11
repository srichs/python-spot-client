"""Async client implementation for interacting with the Spot API."""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import json
import logging
import math
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    TypeVar,
)

import httpx

from .enums import SpotRequestType
from .models import SpotFeed, SpotMessage, _coerce_int

logger = logging.getLogger(__name__)


class SpotRequestStatus(str, Enum):
    """Represents the outcome of a Spot API request."""

    SUCCESS = "success"
    THROTTLED = "throttled"
    TRANSPORT_ERROR = "transport_error"
    DECODE_ERROR = "decode_error"


@dataclass
class SpotRequestResult:
    """Container describing the outcome of a Spot API request."""

    status: SpotRequestStatus
    feed: SpotFeed
    response: Optional[dict] = None
    wait_seconds: Optional[float] = None
    error: Optional[Exception] = None
    request_time: Optional[datetime.datetime] = None
    status_code: Optional[int] = None
    response_headers: Optional[dict] = None
    response_text: Optional[str] = None
    request_url: Optional[str] = None
    request_params: Optional[dict] = None
    request_headers: Optional[dict] = None

    @property
    def succeeded(self) -> bool:
        return self.status is SpotRequestStatus.SUCCESS

    def __bool__(self) -> bool:  # pragma: no cover - convenience wrapper
        return self.succeeded


FeedEntry = tuple[str, Optional[str]]


T = TypeVar("T")


class SpotApi(object):
    """High-level interface for accessing Spot feeds and messages."""

    SPOT_API_ENDPOINT: str = "https://api.findmespot.com/spot-main-web/consumer/rest-api/2.0/public/feed/"
    # Spot asks to wait at least 2.5 minutes between requests of the same feed
    SPOT_API_WAIT_TIME: int = 150
    # Spot asks to wait at least 2 seconds between requests for different feeds
    SPOT_FEED_WAIT_TIME: int = 2
    DEFAULT_PAGE_SIZE: int = 50

    def __init__(
        self,
        feed_list: Iterable[FeedEntry],
        *,
        api_wait_time: float | int = SPOT_API_WAIT_TIME,
        feed_wait_time: float | int = SPOT_FEED_WAIT_TIME,
        client_timeout: httpx.Timeout | float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
        client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        base_endpoint: str = SPOT_API_ENDPOINT,
        default_request_headers: Optional[Mapping[str, str]] = None,
        default_query_params: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._feeds: Dict[str, SpotFeed] = {}
        self._feed_order: List[str] = []
        self._last_request: Dict[str, Optional[datetime.datetime]] = {}
        self._last_response: Dict[str, Optional[dict]] = {}
        self._last_feed_request_time: Optional[datetime.datetime] = None
        self._last_feed_request_id: Optional[str] = None
        self._api_wait_time: float = max(0.0, float(api_wait_time))
        self._feed_wait_time: float = max(0.0, float(feed_wait_time))
        self._client_timeout: httpx.Timeout | float = client_timeout
        self._client: Optional[httpx.AsyncClient] = client
        self._client_factory: Optional[Callable[[], httpx.AsyncClient]] = client_factory
        self._own_client: bool = client is None
        self._base_endpoint: str = self._normalize_endpoint(base_endpoint)
        self._default_headers = self._normalize_headers(default_request_headers)
        self._default_query_params = self._normalize_query_params(default_query_params)

        if client is not None and client_factory is not None:
            raise ValueError("Specify either client or client_factory, not both")

        for feed_id, password in self._normalize_feed_list(feed_list):
            self._register_feed(feed_id, password)

    @property
    def feed(self) -> SpotFeed:
        return self.get_feed()

    @property
    def last_request(self) -> Optional[datetime.datetime]:
        default_feed_id = self._default_feed_id()
        if default_feed_id is None:
            return None
        return self._last_request.get(default_feed_id)

    @property
    def last_response(self) -> Optional[dict]:
        default_feed_id = self._default_feed_id()
        if default_feed_id is None:
            return None
        return self._last_response.get(default_feed_id)

    def get_feed(self, feed_id: Optional[str] = None) -> SpotFeed:
        target_feed_id = feed_id or self._default_feed_id()
        if target_feed_id is None:
            raise ValueError("No feeds configured")
        if target_feed_id not in self._feeds:
            raise ValueError(f"Unknown feed_id: {target_feed_id}")

        return self._feeds[target_feed_id]

    def get_last_response(self, feed_id: Optional[str] = None) -> Optional[dict]:
        target_feed_id = feed_id or self._default_feed_id()
        if target_feed_id is None:
            return None
        return self._last_response.get(target_feed_id)

    def _normalize_feed_list(
        self, feed_list: Iterable[FeedEntry]
    ) -> list[FeedEntry]:
        """Validate and normalize the configured feeds.

        Converting the IDs and passwords to strings up front ensures the rest of the
        client can rely on consistent types and keeps ``__init__`` focused on
        configuration rather than error handling.
        """
        if feed_list is None:
            raise ValueError("feed_list must be provided")

        normalized_feeds = []
        for feed_entry in feed_list:
            try:
                current_feed_id, password = feed_entry
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Each feed entry must contain a feed ID and feed password"
                ) from exc

            feed_id = str(current_feed_id)
            password_value = "" if password is None else str(password)
            normalized_feeds.append((feed_id, password_value))

        if not normalized_feeds:
            raise ValueError("At least one feed must be provided")

        return normalized_feeds

    def _register_feed(self, feed_id: str, password: str) -> None:
        """Create the ``SpotFeed`` and register bookkeeping for it."""
        feed = SpotFeed(feed_id, password)
        self._feeds[feed_id] = feed
        self._feed_order.append(feed_id)
        self._last_request[feed_id] = None
        self._last_response[feed_id] = None

    def _default_feed_id(self) -> Optional[str]:
        """Return the feed identifier used when none is explicitly provided."""
        return self._feed_order[0] if self._feed_order else None

    @staticmethod
    def average_location(
        messages: Iterable[SpotMessage], *, allow_origin: bool = False
    ) -> Optional[tuple[float, float]]:
        """Calculate the average latitude and longitude for a collection of messages.

        Parameters
        ----------
        messages:
            An iterable of :class:`SpotMessage` instances to evaluate.
        allow_origin:
            When ``False`` (the default), coordinates at ``(0.0, 0.0)`` are treated as
            placeholders and ignored. Set to ``True`` to include those points in the
            average calculation.
        """

        total_lat = 0.0
        total_lon = 0.0
        count = 0
        for message in messages:
            latitude = getattr(message, "latitude", None)
            longitude = getattr(message, "longitude", None)
            if latitude is None or longitude is None:
                continue

            try:
                lat_value = float(latitude)
                lon_value = float(longitude)
            except (TypeError, ValueError):
                continue

            if math.isnan(lat_value) or math.isnan(lon_value):
                continue

            if not allow_origin and lat_value == 0.0 and lon_value == 0.0:
                continue

            total_lat += lat_value
            total_lon += lon_value
            count += 1

        if not count:
            return None

        return total_lat / count, total_lon / count

    async def __aenter__(self) -> "SpotApi":
        self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def __enter__(self) -> "SpotApi":
        self._ensure_client()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if self._client_factory is not None:
                client = self._client_factory()
                if not isinstance(client, httpx.AsyncClient):
                    raise TypeError(
                        "client_factory must return an httpx.AsyncClient instance"
                    )
                self._client = client
            else:
                self._client = httpx.AsyncClient(timeout=self._client_timeout)
            self._own_client = True
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._own_client:
            await self._client.aclose()
        self._client = None

    def close(self) -> None:
        """Synchronously close the underlying HTTP client when owned by this instance."""

        self._run_sync(self.aclose())

    async def request(
        self,
        page: int = 1,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        page_size: Optional[int] = None,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Make a request to the Spot API using pagination."""

        feed = self.get_feed(feed_id)
        normalized_page_size = self._normalize_page_size(page_size)
        return await self._request(
            feed,
            page=page,
            merge=merge,
            page_size=normalized_page_size,
            extra_params=extra_params,
            headers=headers,
        )

    def request_sync(
        self,
        page: int = 1,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        page_size: Optional[int] = None,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Synchronous wrapper around :meth:`request` for convenience."""

        return self._run_sync(
            self.request(
                page=page,
                feed_id=feed_id,
                merge=merge,
                page_size=page_size,
                extra_params=extra_params,
                headers=headers,
            )
        )

    async def request_with_dates(
        self,
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Make a request to the Spot API using a datetime range."""

        feed = self.get_feed(feed_id)
        return await self._request(
            feed,
            start_dt=start_dt,
            end_dt=end_dt,
            merge=merge,
            extra_params=extra_params,
            headers=headers,
        )

    def request_with_dates_sync(
        self,
        start_dt: datetime.datetime,
        end_dt: datetime.datetime,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Synchronous wrapper around :meth:`request_with_dates`."""

        return self._run_sync(
            self.request_with_dates(
                start_dt,
                end_dt,
                feed_id=feed_id,
                merge=merge,
                extra_params=extra_params,
                headers=headers,
            )
        )

    async def request_latest(
        self,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        page_size: Optional[int] = None,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Make a request to retrieve the latest message for each device in the feed."""

        feed = self.get_feed(feed_id)
        normalized_page_size = self._normalize_page_size(page_size)
        return await self._request(
            feed,
            SpotRequestType.LATEST,
            merge=merge,
            page_size=normalized_page_size,
            extra_params=extra_params,
            headers=headers,
        )

    def request_latest_sync(
        self,
        feed_id: Optional[str] = None,
        *,
        merge: bool = False,
        page_size: Optional[int] = None,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Synchronous wrapper around :meth:`request_latest`."""

        return self._run_sync(
            self.request_latest(
                feed_id=feed_id,
                merge=merge,
                page_size=page_size,
                extra_params=extra_params,
                headers=headers,
            )
        )

    async def request_all_pages(
        self,
        *,
        feed_id: Optional[str] = None,
        start_page: int = 1,
        merge_existing: bool = False,
        max_throttled_retries: Optional[int] = None,
        page_size: Optional[int] = None,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> AsyncIterator[SpotRequestResult]:
        """Iterate through all available pages for a feed.

        Parameters
        ----------
        feed_id:
            Identifier of the feed to paginate. Defaults to the first configured feed.
        start_page:
            Page number to begin pagination from (1-indexed).
        merge_existing:
            When ``True`` the first page will be merged into the current feed state
            instead of replacing it.
        max_throttled_retries:
            Maximum number of throttled responses to tolerate before aborting the
            pagination loop. ``None`` preserves the previous behaviour of retrying
            indefinitely.
        page_size:
            Number of results requested per page. ``None`` uses the API default of
            ``50``.
        extra_params:
            Additional query parameters to include with each request.
        headers:
            Additional HTTP headers to include with each request.
        """

        if start_page < 1:
            raise ValueError("start_page must be at least 1")

        feed = self.get_feed(feed_id)
        normalized_page_size = self._normalize_page_size(page_size)
        current_page = start_page
        first_iteration = True
        throttle_count = 0

        while True:
            merge_flag = merge_existing if first_iteration else True
            result = await self._request(
                feed,
                request_type=SpotRequestType.MESSAGE,
                page=current_page,
                merge=merge_flag,
                page_size=normalized_page_size,
                extra_params=extra_params,
                headers=headers,
            )
            yield result

            if result.status is SpotRequestStatus.THROTTLED:
                throttle_count += 1
                if max_throttled_retries is not None and throttle_count > max_throttled_retries:
                    logger.warning(
                        "Aborting pagination for feed %s after %s throttled responses",
                        feed.id,
                        throttle_count,
                    )
                    break
                wait_seconds = self._calculate_throttle_wait(
                    throttle_count, result.wait_seconds
                )
                if wait_seconds > 0:
                    logger.debug(
                        "Sleeping %.2f seconds before retrying feed %s page %s",
                        wait_seconds,
                        feed.id,
                        current_page,
                    )
                    await asyncio.sleep(wait_seconds)
                continue

            if result.status is not SpotRequestStatus.SUCCESS:
                break

            first_iteration = False
            throttle_count = 0

            if not self._has_additional_page(
                result.response, page_size=normalized_page_size
            ):
                break

            current_page += 1

    async def _request(
        self,
        feed: SpotFeed,
        request_type: SpotRequestType = SpotRequestType.MESSAGE,
        page: int = 1,
        start_dt: Optional[datetime.datetime] = None,
        end_dt: Optional[datetime.datetime] = None,
        *,
        merge: bool = False,
        page_size: int = DEFAULT_PAGE_SIZE,
        extra_params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> SpotRequestResult:
        """Dispatch a request to the Spot API using the provided parameters."""

        allowed, wait_seconds = self._can_dispatch_request(feed)
        if not allowed:
            logger.debug(
                "Throttling request for feed %s; %.2f seconds remaining", feed.id, wait_seconds
            )
            return SpotRequestResult(
                SpotRequestStatus.THROTTLED,
                feed,
                wait_seconds=max(0.0, wait_seconds),
            )

        try:
            url, payload = self._build_request(
                feed,
                request_type,
                page,
                start_dt,
                end_dt,
                page_size,
                extra_params=extra_params,
            )
        except ValueError as exc:
            logger.error("Invalid Spot API request for feed %s: %s", feed.id, exc)
            raise

        logger.debug(
            "Performing %s request for feed %s with payload=%s",
            request_type,
            feed.id,
            payload,
        )

        payload_copy = dict(payload)
        headers_for_request = self._prepare_headers(headers)
        headers_copy = dict(headers_for_request) if headers_for_request else None

        response = await self._perform_http_request(
            feed,
            url,
            payload,
            headers_for_request,
            payload_copy,
            headers_copy,
        )
        if isinstance(response, SpotRequestResult):
            return response

        return self._handle_successful_response(
            feed,
            response,
            merge,
            url,
            payload_copy,
            headers_copy,
        )

    async def _perform_http_request(
        self,
        feed: SpotFeed,
        url: str,
        payload: Mapping[str, str],
        headers_for_request: Optional[Mapping[str, str]],
        payload_copy: dict,
        headers_copy: Optional[dict],
    ) -> httpx.Response | SpotRequestResult:
        try:
            client = self._ensure_client()
            response = await client.get(url, params=payload, headers=headers_for_request)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception("HTTP error while contacting Spot API")
            return self._transport_error_result(
                feed,
                exc,
                url,
                payload_copy,
                headers_copy,
            )

        return response

    def _handle_successful_response(
        self,
        feed: SpotFeed,
        response: httpx.Response,
        merge: bool,
        url: str,
        payload_copy: dict,
        headers_copy: Optional[dict],
    ) -> SpotRequestResult:
        request_timestamp = self._record_request_timestamp(feed)
        status_code, headers, response_text = self._extract_response_metadata(response)

        try:
            json_response = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            body_preview = response_text[:512] if response_text else ""
            logger.error(
                "Failed to decode Spot API response for feed %s: %s",
                feed.id,
                body_preview,
            )
            return SpotRequestResult(
                SpotRequestStatus.DECODE_ERROR,
                feed,
                error=exc,
                request_time=request_timestamp,
                status_code=status_code,
                response_headers=headers,
                response_text=response_text,
                request_url=url,
                request_params=payload_copy,
                request_headers=headers_copy,
            )

        self._last_response[feed.id] = json_response
        logger.debug("Received response for feed %s", feed.id)
        feed.from_json(json_response, merge=merge)
        return SpotRequestResult(
            SpotRequestStatus.SUCCESS,
            feed,
            response=json_response,
            request_time=request_timestamp,
            status_code=status_code,
            response_headers=headers,
            response_text=response_text,
            request_url=url,
            request_params=payload_copy,
            request_headers=headers_copy,
        )

    def _transport_error_result(
        self,
        feed: SpotFeed,
        exc: httpx.HTTPError,
        url: str,
        payload_copy: dict,
        headers_copy: Optional[dict],
    ) -> SpotRequestResult:
        request_timestamp = self._record_request_timestamp(feed)
        response_obj = getattr(exc, "response", None)
        status_code, headers, body_text = self._extract_response_metadata(response_obj)

        if status_code == 429:
            wait_seconds = self._retry_after_seconds(response_obj)
            logger.warning(
                "Received HTTP 429 from Spot API for feed %s; retrying after %.2f seconds",
                feed.id,
                wait_seconds,
            )
            return SpotRequestResult(
                SpotRequestStatus.THROTTLED,
                feed,
                wait_seconds=wait_seconds,
                request_time=request_timestamp,
                status_code=status_code,
                response_headers=headers,
                response_text=body_text,
                request_url=url,
                request_params=payload_copy,
                request_headers=headers_copy,
            )

        return SpotRequestResult(
            SpotRequestStatus.TRANSPORT_ERROR,
            feed,
            error=exc,
            request_time=request_timestamp,
            status_code=status_code,
            response_headers=headers,
            response_text=body_text,
            request_url=url,
            request_params=payload_copy,
            request_headers=headers_copy,
        )

    def _record_request_timestamp(self, feed: SpotFeed) -> datetime.datetime:
        request_timestamp = self._now()
        self._last_request[feed.id] = request_timestamp
        self._last_feed_request_time = request_timestamp
        self._last_feed_request_id = feed.id
        return request_timestamp

    def _extract_response_metadata(
        self, response: Optional[httpx.Response]
    ) -> tuple[Optional[int], Optional[dict], Optional[str]]:
        if response is None:
            return None, None, None

        status_code = getattr(response, "status_code", None)
        raw_headers = getattr(response, "headers", None)
        headers = None
        if raw_headers is not None:
            try:
                headers = dict(raw_headers)
            except Exception:  # pragma: no cover - defensive
                headers = None

        try:
            response_text = response.text
        except Exception:  # pragma: no cover - defensive
            response_text = None

        return status_code, headers, response_text

    def _normalize_page_size(self, page_size: Optional[int]) -> int:
        if page_size is None:
            return self.DEFAULT_PAGE_SIZE

        try:
            normalized = int(page_size)
        except (TypeError, ValueError) as exc:
            raise ValueError("page_size must be an integer") from exc

        if normalized < 1:
            raise ValueError("page_size must be at least 1")

        return normalized

    def _has_additional_page(
        self, response: Optional[dict], page_size: int = DEFAULT_PAGE_SIZE
    ) -> bool:
        if not response:
            return False

        try:
            feed_message_response = response["response"]["feedMessageResponse"]
        except (KeyError, TypeError):
            return False

        if not isinstance(feed_message_response, dict):
            return False

        count_value = _coerce_int(feed_message_response.get("count", 0))
        total_count_value = _coerce_int(feed_message_response.get("totalCount", 0))
        start_index_value = _coerce_int(feed_message_response.get("start", 0))

        count = count_value if count_value is not None else 0
        total_count = total_count_value if total_count_value is not None else 0
        start_index = start_index_value if start_index_value is not None else 0

        if total_count and start_index:
            # `start` is 1-indexed in the Spot API payload.
            return start_index + count - 1 < total_count

        # Fall back to the API's documented default page size.
        return count >= page_size

    def _retry_after_seconds(self, response: Optional[httpx.Response]) -> float:
        default_wait = max(0.0, float(self._api_wait_time))

        if response is None:
            return default_wait

        try:
            retry_after = response.headers.get("Retry-After") if response.headers else None
        except Exception:  # pragma: no cover - defensive
            retry_after = None

        if not retry_after:
            return default_wait

        value = retry_after.strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_dt = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                logger.warning("Unable to parse Retry-After header value '%s'", value)
                return default_wait

            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=datetime.timezone.utc)

            wait_seconds = (retry_dt - self._now()).total_seconds()
            return max(0.0, wait_seconds)

        return max(0.0, seconds)

    def _can_dispatch_request(self, feed: SpotFeed) -> tuple[bool, float]:
        inter_feed_remaining = self._inter_feed_wait_remaining(feed)
        if inter_feed_remaining > 0.0:
            return False, inter_feed_remaining

        request_remaining = self._request_wait_remaining(feed)
        if request_remaining > 0.0:
            return False, request_remaining

        return True, 0.0

    def _build_request(
        self,
        feed: SpotFeed,
        request_type: SpotRequestType = SpotRequestType.MESSAGE,
        page: int = 1,
        start_dt: Optional[datetime.datetime] = None,
        end_dt: Optional[datetime.datetime] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        *,
        extra_params: Optional[Mapping[str, str]] = None,
    ) -> tuple[str, dict]:
        payload = self._get_base_payload(feed)

        if page_size < 1:
            raise ValueError("page_size must be at least 1")

        if request_type == SpotRequestType.LATEST:
            if start_dt is not None or end_dt is not None:
                raise ValueError("Date ranges are not supported for latest requests")
            if page != 1:
                raise ValueError("Pagination is not supported for latest requests")
            if extra_params:
                self._apply_extra_params(payload, extra_params)
            return self._get_request_url(feed, SpotRequestType.LATEST), payload

        if page < 1:
            raise ValueError("Page number must be at least 1")

        if (start_dt is None) ^ (end_dt is None):
            raise ValueError("Both start and end datetimes must be provided together")

        if start_dt and end_dt:
            if end_dt < start_dt:
                raise ValueError("End datetime must be greater than or equal to start datetime")

            payload["startDate"] = self._format_request_datetime(start_dt)
            payload["endDate"] = self._format_request_datetime(end_dt)
        elif page > 1:
            payload["start"] = str((page - 1) * page_size + 1)

        payload["pageSize"] = str(page_size)

        if extra_params:
            self._apply_extra_params(payload, extra_params)

        return self._get_request_url(feed, SpotRequestType.MESSAGE), payload

    def _get_request_url(
        self,
        feed: SpotFeed,
        request_type: SpotRequestType = SpotRequestType.MESSAGE,
    ) -> str:
        """Return the URL used to request Spot feed data."""

        if request_type == SpotRequestType.LATEST:
            return f"{self._base_endpoint}{feed.id}/latest.json"
        else:
            return f"{self._base_endpoint}{feed.id}/message.json"

    def _prepare_headers(
        self, extra_headers: Optional[Mapping[str, str]]
    ) -> Optional[Dict[str, str]]:
        headers: Dict[str, str] = (
            dict(self._default_headers) if self._default_headers else {}
        )

        normalized_extra = self._normalize_headers(extra_headers)
        if normalized_extra:
            headers.update(normalized_extra)

        return headers or None

    def _apply_extra_params(
        self, payload: Dict[str, str], extra_params: Mapping[str, str]
    ) -> None:
        normalized_params = self._normalize_query_params(extra_params)
        if not normalized_params:
            return

        payload.update(normalized_params)

    def _calculate_throttle_wait(
        self, throttle_count: int, explicit_wait: Optional[float]
    ) -> float:
        if explicit_wait is not None and explicit_wait > 0:
            base_wait = float(explicit_wait)
        else:
            base_wait = max(float(self._feed_wait_time), 1.0)

        multiplier = max(1, throttle_count)
        wait_time = base_wait * (2 ** (multiplier - 1))
        max_wait = max(base_wait, float(self._api_wait_time))

        if explicit_wait is not None and explicit_wait > 0:
            return max(0.0, float(explicit_wait))

        return max(0.0, min(wait_time, max_wait))

    @staticmethod
    def _normalize_headers(
        headers: Optional[Mapping[str, str]]
    ) -> Optional[Dict[str, str]]:
        if headers is None:
            return None
        normalized: Dict[str, str] = {}
        for key, value in headers.items():
            if value is None:
                continue
            normalized[str(key)] = str(value)
        return normalized or None

    @staticmethod
    def _normalize_query_params(
        params: Optional[Mapping[str, str]]
    ) -> Optional[Dict[str, str]]:
        if params is None:
            return None
        normalized: Dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            normalized[str(key)] = str(value)
        return normalized or None

    def _get_base_payload(self, feed: SpotFeed) -> dict:
        """Return the base payload for a Spot API request."""

        payload: Dict[str, str] = {}
        if self._default_query_params:
            payload.update(self._default_query_params)
        if feed.password:
            payload["feedPassword"] = feed.password
        return payload

    def _request_wait_remaining(self, feed: SpotFeed) -> float:
        last_request = self._last_request.get(feed.id)
        if last_request is None:
            return 0.0

        elapsed_seconds = (self._now() - last_request).total_seconds()
        remaining = self._api_wait_time - elapsed_seconds

        if remaining <= 0.0:
            logger.debug("Request wait time elapsed for feed %s", feed.id)
            return 0.0

        logger.debug(
            "Request wait time has not elapsed for feed %s (elapsed=%s)",
            feed.id,
            elapsed_seconds,
        )
        return remaining

    def _inter_feed_wait_remaining(self, feed: SpotFeed) -> float:
        if self._last_feed_request_time is None:
            return 0.0

        if self._last_feed_request_id == feed.id:
            return 0.0

        elapsed_seconds = (self._now() - self._last_feed_request_time).total_seconds()
        remaining = self._feed_wait_time - elapsed_seconds

        if remaining <= 0.0:
            return 0.0

        logger.debug(
            "Inter-feed wait time has not elapsed between %s and %s (elapsed=%s)",
            self._last_feed_request_id,
            feed.id,
            elapsed_seconds,
        )
        return remaining

    @staticmethod
    def _format_request_datetime(dt: datetime.datetime) -> str:
        if dt.tzinfo is None:
            raise ValueError(
                "Naive datetimes are not supported; provide an aware datetime with timezone information"
            )

        normalized = dt.astimezone(datetime.timezone.utc)
        return normalized.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _run_sync(self, awaitable: Awaitable[T]) -> T:
        """Execute an awaitable synchronously using ``asyncio.run`` when possible."""

        async def runner() -> T:
            try:
                return await awaitable
            finally:
                await self._reset_client_after_sync_run()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(runner())

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, runner())
            return future.result()

    async def _reset_client_after_sync_run(self) -> None:
        if not self._own_client:
            return

        client = self._client
        self._client = None

        if client is None:
            return

        try:
            await client.aclose()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.warning("Failed to close AsyncClient after synchronous run", exc_info=True)

    @staticmethod
    def _now() -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        if not endpoint:
            raise ValueError("base_endpoint must be a non-empty string")

        normalized = endpoint.rstrip("/") + "/"
        return normalized

    def __str__(self) -> str:
        return "\n".join(str(self._feeds[feed_id]) for feed_id in self._feed_order)


__all__ = ["SpotApi", "SpotRequestResult", "SpotRequestStatus"]
