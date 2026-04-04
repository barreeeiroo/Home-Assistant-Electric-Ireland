# TESTS

## OVERVIEW

9 test files + 2 conftest, ~3,700 lines, >=95% coverage. Uses `pytest-homeassistant-custom-component` for HA test harness, `aioresponses` for HTTP mocking. All tests are async (`asyncio_mode = "auto"`).

## STRUCTURE

```
tests/
├── conftest.py                     # Shared fixtures: mock_config_entry, mock_api, mock_setup_entry
│                                   # + pycares daemon thread prevention (module-level patch)
├── test_api.py                     # API client tests (37 tests, 630 lines)
├── test_coordinator.py             # Coordinator + statistics tests (22 tests, 898 lines)
├── test_config_flow.py             # Config flow tests (20 tests, 608 lines)
├── test_sensor.py                  # Diagnostic sensor tests (9 tests, 138 lines)
├── test_init.py                    # Setup/unload/migration tests (4 tests, 111 lines)
├── test_diagnostics.py             # Diagnostics redaction tests (4 tests, 89 lines)
├── fixtures/
│   └── sample_hourly_response.json # 24 hourly datapoints with consumption/cost
├── integration/                    # Real integration tests (aioresponses only, no mocked internals)
│   ├── conftest.py                 # HTML/JSON builders, mock_ei_http helper
│   ├── test_flows.py              # Config flow integration tests (12 tests, 436 lines)
│   ├── test_lifecycle.py          # Setup/unload/migration integration tests (11 tests, 368 lines)
│   └── test_api.py                # Account discovery + meter data fetch (17 tests, 242 lines)
└── __init__.py                     # Empty
```

## MOCKING STRATEGY (MINIMAL — EXTERNAL BOUNDARIES ONLY)

| What to Mock | How | Why |
|-------------|-----|-----|
| HTTP requests | `aioresponses` (`.get()`, `.post()`) | External boundary: Electric Ireland website |
| Config entries | `MockConfigEntry` from `pytest_homeassistant_custom_component.common` | HA internal: entry lifecycle |
| Recorder | `recorder_mock` fixture | HA internal: statistics storage |
| Time | `freezegun` / `async_fire_time_changed` | Deterministic time-dependent tests |
| API client class | `unittest.mock.AsyncMock` + `patch` | Isolate coordinator from API (unit tests only) |

**NEVER mock**: HTML parsing, statistics calculation, config flow validation logic, coordinator update logic, entity value computation.

## UNIT TESTS vs INTEGRATION TESTS

| Aspect | Unit (`tests/test_*.py`) | Integration (`tests/integration/`) |
|--------|--------------------------|-------------------------------------|
| API | Mocked via `AsyncMock` + `patch` | Real — only HTTP intercepted by `aioresponses` |
| Config flow | Mocked `async_setup_entry` | Real HA machinery (with `mock_setup_entry` to prevent coordinator side effects) |
| Coordinator | Mocked API responses | Real coordinator + real recorder |
| HTML parsing | Real | Real |
| Coverage | Targets individual modules | Tests end-to-end flows |

## FIXTURE PATTERNS

### Root conftest.py Fixtures

- **`mock_config_entry`**: Creates `MockConfigEntry` with domain, version=2, test credentials, and meter IDs. Unique ID set to account number.
- **`mock_api`**: Patches `ElectricIrelandAPI` with `AsyncMock` returning test data. Used for coordinator and init tests.
- **`mock_setup_entry`**: Patches `async_setup_entry` to skip full integration setup during config flow tests.
- **pycares patch** (module-level): Disables `pycares._ChannelShutdownManager.start` to prevent `_run_safe_shutdown_loop` daemon thread that trips `verify_cleanup` on `pytest-homeassistant-custom-component` <0.13.316.

### Integration conftest.py

- **`mock_ei_http(m, ...)`**: Configures `aioresponses` with realistic Electric Ireland HTML pages + MeterInsight API responses.
- **`page()`, `acct_div()`, `insights_page()`**: HTML builders for login page, account dashboard, and insights page.
- **`session`**: Creates `aiohttp.ClientSession` with `CookieJar` for API-level tests.

### JSON Fixtures

- **`fixtures/sample_hourly_response.json`**: Realistic API response with 24 hourly entries, each containing consumption (kWh), cost (EUR), and tariff bucket data.

## TEST-BY-TEST GUIDE

### Unit Tests

| File | Tests | What It Validates |
|------|-------|-------------------|
| `test_api.py` | 37 | Login flow (CSRF extraction, POST, redirects), account discovery (scraping account divs), hourly data fetch (JSON parsing, tariff selection), error handling (auth failure, connection error, missing accounts, stale cached IDs) |
| `test_coordinator.py` | 22 | First refresh (30-day backfill), subsequent refresh (7-day lookback), statistics import (cumulative sums, overlap detection), auth failure → `ConfigEntryAuthFailed`, connection failure → `UpdateFailed`, meter ID caching, state logging transitions |
| `test_config_flow.py` | 20 | User step (happy path, invalid auth, connection error, unknown error), account selection (single/multiple accounts), reauth flow (success, failure), reconfigure flow (password change, meter ID rediscovery), unique ID abort |
| `test_sensor.py` | 9 | Entity creation, native_value correctness, unique_id format, device_info structure, entity_category = DIAGNOSTIC, disabled_by_default = True |
| `test_init.py` | 4 | Setup success, unload success, v1→v2 migration, setup failure handling |
| `test_diagnostics.py` | 4 | Diagnostics data structure, credential redaction, meter ID redaction, coordinator data inclusion |

### Integration Tests

| File | Tests | What It Validates |
|------|-------|-------------------|
| `test_flows.py` | 12 | Full config flow with real HTML parsing: single/multi account, reauth, reconfigure, error recovery, duplicate abort |
| `test_lifecycle.py` | 11 | Full setup→refresh→unload cycle, meter ID discovery + caching, multi-account isolation, v1→v2 migration, auth/connection failure handling |
| `test_api.py` | 17 | Account discovery from real HTML, hourly meter data fetch with real JSON parsing |

## CONVENTIONS

- **Naming**: `test_{module}.py` mirrors integration module names.
- **Async**: All test functions are async by default (`asyncio_mode = "auto"` in pyproject.toml). No `@pytest.mark.asyncio` needed.
- **Fixtures**: Shared fixtures in `conftest.py`. Test-specific fixtures inline in test files.
- **Assertions**: Direct `assert` statements. Use `pytest.raises` for expected exceptions.
- **Statistics verification**: Use `get_instance(hass).async_add_executor_job(statistics_during_period, ...)` to verify recorder state.
- **Coverage**: `--cov-fail-under=95` enforced in CI. `types.py` is excluded (TypedDict-only file).

## TDD WORKFLOW (MANDATORY)

Every code change follows this cycle:

1. **RED**: Write a failing test that captures expected behavior
2. **GREEN**: Write minimal code to pass the test
3. **REFACTOR**: Clean up, tests must stay green
4. **VERIFY**: `pytest tests/ --cov-fail-under=95 -q && mypy --strict && ruff check custom_components/ tests/`

## ANTI-PATTERNS

- **NEVER** mock internal logic (HTML parsing, stat calculation, coordinator update flow).
- **NEVER** skip coverage checks — CI enforces >=95%.
- **NEVER** use `@pytest.mark.asyncio` — `asyncio_mode = "auto"` handles it.
- **NEVER** create real network connections in tests — always `aioresponses`.
- **NEVER** delete or weaken tests to make CI pass — fix the code.

## Test Strategy: Tradeoffs & Limitations

### Realism vs Speed
- Integration tests run through real HA + recorder (in-memory SQLite): ~0.5-1s each
- Unit tests use mocked API: ~0.01s each
- Tradeoff accepted: correctness > speed

### Real Fixtures vs Synthetic
- `tests/fixtures/real/` — anonymized + perturbed from real EI account (capture script)
- `tests/fixtures/` — synthetic edge cases (empty day, partial day, bill period gaps)
- Real fixtures catch format/structure bugs; synthetic catch logic bugs. Both needed.

### Anonymization Boundary
- Account numbers, emails, meter IDs: replaced with placeholders
- Consumption/cost values: randomly perturbed (0.7-1.3x) to destroy behavioral fingerprint
- HTML structure: anonymized but preserved (CSS classes, form layout)

### HTML Resilience Limitation
- Tests verify specific HTML variations (extra classes, nested elements, missing divs)
- Cannot predict ALL future EI website changes
- Failures are intentional early warning, not flakiness

### DST Limitation
- Integration works entirely in UTC
- DST tests require real fixture capture (skip-marked until available)
- Spring-forward (23h) and fall-back (25h) scenarios depend on EI backend behavior

### Fixture Staleness
- Fixtures are captured once, not auto-refreshed
- Re-run `scripts/capture_fixtures.py` if EI changes API response format
- Stale fixtures may cause false passes — real API integration should be tested periodically

### Known Bug: >2-Day Data Gap
- `coordinator.py:454` uses 2-day lookback window for cumulative sum base
- HA offline >2 days → base_sum resets to 0 → Energy Dashboard cliff
- Test marked `@pytest.mark.xfail` — filed as known issue

### What These Tests Don't Cover
- Performance under load
- UI rendering in Energy Dashboard
- Concurrent multi-user access
- Rate limiting behavior (requires real API)
- Credential rotation
- Property-based testing / fuzzing
