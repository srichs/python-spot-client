# python-spot-client: 80% Understanding Overview

## What it is / Who it's for
**python-spot-client** is an asynchronous Python library for interacting with the [SPOT device API](https://www.findmespot.com/en-us/support/spot-gen4/get-help/general/public-api-and-xml-feed). It targets developers who need to fetch or manage data from SPOT GPS tracker/satellite messaging devices, supporting both synchronous and asynchronous Python code.

## Key Features (Verified by Code)
- **Async and sync APIs:** Core `SpotApi` class exposes async methods (e.g., `await client.request_latest()`) and tested sync wrappers (e.g., `client.request_latest_sync()`).
- **Data models:** Strongly-typed dataclasses represent messages (`SpotMessage`) and feeds (`SpotFeed`). These support parsing, aggregation, filtering, and robust handling of malformed or missing data.
- **Pagination & Time Range:** Methods support paginated fetching (`request_all_pages`) and time-windowed queries (`request_with_dates` and variants).
- **Request throttling:** Built-in rate limit enforcement; API responses include throttling status/enums and wait recommendations via `SpotRequestStatus.THROTTLED`.
- **Aggregation/filter helpers:** Model helpers provide averaging methods (e.g. `average_location`), type filtering, latest-per-device matchup, sorted iteration, and more—all tested in `tests/test_spot_api.py`.
- **Type-checked enums:** Enums cover battery state, device/message/feed types, request statuses, and more (`src/spot_api/enums.py`). Mappings from external values to enums are robust, with unrecognized cases logged as warnings.
- **Client hygiene:** Works as a context manager (async or sync); can use a provided or managed httpx.AsyncClient. Handles proper connection management.

## Architecture Overview
- **Public API:** Defined in `src/spot_api/__init__.py`, exposing client, models, enums, and internal helpers.
- **Client logic:** `src/spot_api/client.py` implements transport, API state/rate limiting, parameter handling, and endpoint logic.
- **Data parsing/models:** `src/spot_api/models.py` defines `SpotFeed` and `SpotMessage`, with rich parsing, type coercion, and helper methods.
- **Enums:** `src/spot_api/enums.py` contains all enum classes (for request types, battery, device/feed/message types, and statuses). All enums have `.from_str()` classmethods for safe construction from API values, and logging for unrecognized input.
- **Testing focus:** Core business logic (API, models, enums, and coercion/parsing helpers) is covered by unit tests in `tests/test_spot_api.py`, with coverage for error-handling, sync/async logic, parsing, averaging/location math, and all enum mappings.

## Execution Model / Entrypoints
- **Library use only:** No CLI or standalone entrypoint. Main usage: import `SpotApi` and other types in Python. Key user methods include `request_latest()`, `request_all_pages()`, and aggregation helpers on models.

## How to Run Locally
- **Python 3.11+ required**
- **Install:** `pip install python-spot-client` for use; for development: clone, then `pip install -e .[docs,test,lint]` or use `requirements-dev.txt`.
- **Tests:** Run with `pytest` (mainly in `tests/test_spot_api.py`).
- **Docs:** Build with Sphinx (`make html` in `docs/`).

## Config / Environment Variables
- **Feeds provided at runtime** as list of `(feed_id, password)`. Password is optional per feed but must be explicitly set (`None` is allowed for public feeds). Code and tests enforce that creds should not be hardcoded.
- **No built-in config/env loader:** User is responsible for managing secrets and runtime feed config.

## Data Flow / API / DB
- **All data:** Pulled from SPOT REST API over HTTP using `httpx.AsyncClient`. No secondary DB or persistent queue; strong typing for results returned from `SpotApi` methods.

## Extension Points / Where to Start Reading
- **Entry:** `src/spot_api/client.py` (`SpotApi`)
- **Models:** `src/spot_api/models.py` (`SpotFeed`, `SpotMessage`)
- **Enums:** `src/spot_api/enums.py` (battery, device, feed, message types and statuses)
- **Public API Surface:** `src/spot_api/__init__.py`

## Risks / Gotchas (Explicit from Code & Tests)
- **Async/sync duality:** Both modes are fully supported and tested, but edge case test coverage of rare network faults or deep async context handling is not exhaustively reviewed.
- **API throttling:** Spot API rate limits are strictly enforced. Throttling status is reported, and suggested wait times included.
- **Parsing issues:** Malformed or missing datetimes/coords fallback to safe defaults (e.g., origin, 0/None) with warnings. Unrecognized enums are mapped to `UNKNOWN_*` values and log a warning. Tests verify this behavior for all enums and parsing.
- **Secrets:** User manages secret lifecycles externally—no in-repo secret management or helpers.

## Test Coverage Insights (from tests/test_spot_api.py)
- **Parsing/coercion:** Tests for boolean, float, int, and datetime coercers; verify warning logs on invalid input.
- **Enum robustness:** Each enum's `.from_str()` covers known, unknown, case-variation, and edge cases; logs are asserted.
- **SpotApi edge cases:** Handles duplicate feeds, missing/empty lists, custom endpoints, and aggregation math (with missing/invalid messages).
- **Model utility:** Message parsing, coordinate clamping, short date/loc formatting, and feed construction from realistic API samples are all covered.
- **No integration/system tests:** Coverage is thorough at the unit/surface API level, but not proven for full network or multi-feed integration.

## Suggested First 3 Files to Read
1. `src/spot_api/client.py` (SpotApi core implementation)
2. `src/spot_api/models.py` (Feed/Message models)
3. `src/spot_api/enums.py` (Enum type safety and robust mappings)

## Additional Open Questions
- Are there edge cases in deep async context handling or network retries that lack coverage?
- How does logging scale in high-throughput or multi-feed scenarios—does it flood for unrecognized inputs?
- Are there plans for system/integration test coverage or just unit tests going forward?


# Reading plan

Get productive with python-spot-client by following this step-by-step guide. The plan focuses on vital library logic, usage, and safe extension, and balances deep dives with surface-level orientation.

1. **src/spot_api/client.py**
   _Why it matters:_ Core implementation of the SpotApi client—most business logic lives here.
   _What to look for:_
   - Async and sync API surface (core methods, context manager behavior)
   - Rate limiting/throttling logic
   - How API params and responses are handled
   _Time estimate:_ 20 min

2. **src/spot_api/models.py**
   _Why it matters:_ All main data structures, parsing, aggregation, and helpers are defined here.
   _What to look for:_
   - SpotFeed and SpotMessage classes (fields, parsing, helper methods)
   - Parsing/coercion strategies for incoming API data
   - Aggregation and formatting utilities
   _Time estimate:_ 18 min

3. **src/spot_api/enums.py**
   _Why it matters:_ Houses all key enums, including type safety and robust mapping from API responses.
   _What to look for:_
   - Enum class definitions (battery, device, message, feed, status)
   - `.from_str()` construction and handling of unknowns
   - Logging/warning mechanisms for unrecognized values
   _Time estimate:_ 12 min

4. **src/spot_api/__init__.py**
   _Why it matters:_ Defines the public API, what users are meant to import and how.
   _What to look for:_
   - What is exposed explicitly
   - Any init-time configuration or import-time side effects
   _Time estimate:_ 3 min

5. **tests/test_spot_api.py**
   _Why it matters:_ Unit test coverage for core logic, edge cases, and robustness.
   _What to look for:_
   - Test coverage of API methods (positive and edge cases)
   - Enum mapping/robustness, error handling, parsing failure handling
   - Aggregation and helper function behaviors
   _Time estimate:_ 15 min

6. **README.md**
   _Why it matters:_ User-facing guide for installation, supported features, and minimal usage.
   _What to look for:_
   - Package purpose and installation instructions
   - Feature overview and typical usage
   - Any environment or runtime requirements
   _Time estimate:_ 4 min

7. **requirements.txt** and **pyproject.toml**
   _Why it matters:_ Declares dependencies and packaging; helpful for setting up dev/test environments.
   _What to look for:_
   - Required Python version and main dependencies
   - Extra requirements for testing or documentation
   _Time estimate:_ 3 min

8. **setup.py**
   _Why it matters:_ Contains legacy build/packaging metadata, sometimes with extra notes.
   _What to look for:_
   - Package metadata for distribution
   - Any custom install or setup logic
   _Time estimate:_ 2 min

9. **.github/workflows/ci.yml**
   _Why it matters:_ Shows the continuous integration pipeline for running tests and lint checks.
   _What to look for:_
   - How tests are executed; Python version(s) covered
   - Linting, coverage, and build triggers
   _Time estimate:_ 3 min

---

## If you only have 30 minutes
1. **Read `src/spot_api/client.py`** (skim core methods, context manager, throttling) — 12 min
2. **Read `src/spot_api/models.py`** (only data class definitions/constructor and key helpers) — 8 min
3. **Glance at `tests/test_spot_api.py`** (skim test case structure and edge cases) — 6 min


## If you need to make a change safely
- **How to run tests/build:**
  - Install dev requirements: `pip install -e .[docs,test,lint]` or use `requirements-dev.txt`.
  - Run tests with: `pytest tests/test_spot_api.py`
- **Where to add a small change and validate quickly:**
  - For core logic: add/change a method in `src/spot_api/client.py`.
  - Quickly validate by adding or modifying a test case in `tests/test_spot_api.py` and running `pytest`.
- **What to verify:**
  - Ensure all tests pass (including edge and error cases).
  - If modifying parsing/mapping: check warnings/logs for malformed input as tested in the suite.