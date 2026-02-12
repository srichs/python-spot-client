# python-spot-client

[![CI](https://github.com/srichs/python-spot-client/actions/workflows/ci.yml/badge.svg)](https://github.com/srichs/python-spot-client/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/python-spot-client.svg)](https://pypi.org/project/python-spot-client/)

An asynchronous Python client for retrieving message feeds from the [SPOT device API](https://www.findmespot.com/en-us/support/spot-gen4/get-help/general/public-api-and-xml-feed).

## Features

- Simple asynchronous wrapper around the SPOT device feed endpoints, with optional synchronous entry points for quick scripts.
- Data classes that model devices, feeds, and messages returned by the API.
- Helpers for retrieving the latest messages, paginated history, or data within a time window.

## Installation

Install the package from the repository root in your current environment:

```bash
pip install .
```

For local development install the runtime dependencies together with the
documentation, test, and linting extras:

```bash
pip install -e .[docs,test,lint]
```

Or use the convenience dev requirements file:

```bash
pip install -r requirements-dev.txt
```

## Quick start

To authenticate requests, pass one or more `(feed_id, password)` tuples when
creating the client.

The client wraps the SPOT REST API and exposes models that make it easier to
inspect devices, feeds, and messages. The example below fetches the latest
messages from a feed and prints each device's most recent location.

```python
import asyncio
from spot_api import SpotApi


async def main():
    feed_list = [("<your-feed-id>", "<feed-password>")]

    async with SpotApi(feed_list) as client:
        await client.request_latest()

        for message in client.feed.get_latest_messages():
            print(
                f"Device {message.messenger_name} "
                f"({message.messenger_id}) at {message.get_location()} "
                f"on {message.date_time}"
            )


if __name__ == "__main__":
    asyncio.run(main())
```

## Usage

For scripts that do not already run an event loop, call the synchronous
wrappers instead:

```python
with SpotApi([("<your-feed-id>", "<feed-password>")]) as client:
    result = client.request_latest_sync()
```

Or manage lifecycle manually:

```python
client = SpotApi([("<your-feed-id>", "<feed-password>")])
result = client.request_latest_sync()
client.close()
```

The synchronous helpers still rely on the underlying asynchronous client. The
context manager handles teardown automatically, and the explicit `close`
method runs the same asynchronous shutdown under the hood. If you provide your
own `httpx.AsyncClient`, `close` and the context manager will leave it alone so
you can manage its lifecycle yourself.

### Handling SPOT throttling

SPOT requests that clients wait at least 2.5 minutes (150 seconds) between
requests for the same feed and a couple of seconds when switching between
different feeds. The client tracks these windows automatically and will return a
`SpotRequestResult` with status `SpotRequestStatus.THROTTLED` when you should
pause. Inspect the accompanying `wait_seconds` value to determine how long to
sleep before retrying:

```python
import asyncio

from spot_api import SpotApi, SpotRequestStatus


async def main() -> None:
    async with SpotApi([("<feed-id>", "<password>")]) as client:
        result = await client.request()
        if result.status is SpotRequestStatus.THROTTLED:
            await asyncio.sleep(result.wait_seconds)


if __name__ == "__main__":
    asyncio.run(main())
```

When the SPOT API responds with HTTP 429, the same status is returned together
with an estimated wait. The exponential backoff used by
`SpotApi.request_all_pages` will never exceed the documented 150 second window.

### Requesting paginated history

To fetch paginated historical results instead of just the latest message, call
`SpotApi.request` and pass the `page` number you need:

```python
await client.request(page=2)
```

You can also iterate every available page with retry-aware pagination. The
iterator yields a `SpotRequestResult` after each request, allowing you to react
to throttling events before the next page is requested:

```python
async for result in client.request_all_pages(merge_existing=True):
    if result.status is SpotRequestStatus.THROTTLED:
        await asyncio.sleep(result.wait_seconds)
        continue

    if result.succeeded:
        # Feed data is merged into client.feed automatically.
        print(f"Fetched page with {len(client.feed.get_latest_messages())} messages")
```

### Requesting a date range

If you know the exact time window to inspect, provide start and end datetimes
using `request_with_dates`:

```python
import datetime

start = datetime.datetime(2023, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
end = datetime.datetime(2023, 1, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
await client.request_with_dates(start, end)
```

The `SpotFeed` object associated with the `SpotApi` instance is populated after
any request. Inspect its `devices` dictionary or use helper methods such as
`get_latest_messages`, `iter_messages`, or `iter_messages_by_type` to work with
the returned data.

### Interpreting request results

Every request helper returns a `SpotRequestResult` object containing:

- `status`: the high-level result state (for example success or throttled).
- `succeeded`: convenience boolean equivalent to a successful status.
- `wait_seconds`: recommended wait time when requests are throttled.

This makes it straightforward to branch on status without parsing exceptions or
raw HTTP responses.

### Working with feeds and messages

`SpotFeed` and `SpotMessage` provide several convenience helpers for common
inspection patterns:

- `SpotFeed.get_latest_messages()` returns a list of the newest message per
  device.
- `SpotFeed.iter_messages()` yields every message across the feed in
  reverse-chronological order, while `iter_messages_by_type()` filters by the
  message type string.
- `SpotMessage.get_location()` formats the message's coordinates into a
  human-readable string (for example, `"34.05, -118.25, 100"`).

These utilities make it easier to work with the deserialized data classes
without needing to remember the raw JSON structure returned by SPOT.

## Documentation

Project documentation is generated with [Sphinx](https://www.sphinx-doc.org/)
using the inline module docstrings. Install the documentation extras and build
the HTML output locally:

```bash
pip install -e .[docs]
cd docs
make html
```

or

```bash
python -m sphinx -b html docs/ docs/build
```

The generated site will be available under `docs/build/index.html` and
includes a short quick-start tour alongside the full API reference.

## API references

- Library API reference: generated documentation in the `docs/` directory (see above).
- Official SPOT public API reference: [Public API and XML feed documentation](https://www.findmespot.com/en-us/support/spot-gen4/get-help/general/public-api-and-xml-feed).

## Development

This project requires Python 3.11 or newer. After installing the test and lint
extras (`pip install -e .[test,lint]`), run the unit tests with:

```bash
pytest
```

The project metadata and build configuration live in `pyproject.toml`. Static
analysis helpers (mypy and ruff) are also included in the `lint` optional
dependency group.

## Security notes

- Treat feed passwords like credentials; avoid committing them to source
  control.
- Prefer environment variables or a local secrets manager for production usage
  instead of hard-coding feed credentials directly in scripts.
