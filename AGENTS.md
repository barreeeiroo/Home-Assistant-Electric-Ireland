# PROJECT KNOWLEDGE BASE

## OVERVIEW

Home Assistant custom integration (HACS) for **Electric Ireland Insights**. Scrapes Electric Ireland's website to import hourly energy consumption (kWh) and cost (EUR) as external statistics into HA's recorder for the Energy Dashboard. Python 3.12+, async throughout, mypy strict.

## STRUCTURE

```
.
├── custom_components/electric_ireland_insights/   # The integration (see its own AGENTS.md)
├── tests/                                         # All tests (see its own AGENTS.md)
├── docs/index.md                                  # HA-format integration documentation
├── brands/README.md                               # Branding assets (pending HA brands repo submission)
├── .github/workflows/validate.yml                 # CI: hassfest, HACS, ruff, mypy, tests (3.12/3.13)
├── .github/dependabot.yml                         # Automated dependency updates (pip + actions)
├── .pre-commit-config.yaml                        # Pre-commit hooks: ruff, mypy, codespell, whitespace
├── pyproject.toml                                 # Build config, dev deps, ruff + mypy + pytest settings
├── mise.toml                                      # Dev env: Python 3.14, auto .venv
├── hacs.json                                      # HACS metadata (requires HA 2025.4.0, HACS 2.0.0)
└── requirements.txt                               # Pip requirements
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Integration source | `custom_components/electric_ireland_insights/` | 13 files, see sub-AGENTS.md |
| Tests | `tests/` | 9 test files + 2 conftest, see sub-AGENTS.md |
| CI pipeline | `.github/workflows/validate.yml` | hassfest, HACS, ruff, mypy, pytest --cov-fail-under=95 |
| HA-format docs | `docs/index.md` | For home-assistant.io submission |
| Quality compliance | `custom_components/.../quality_scale.yaml` | 52-rule IQS self-assessment |
| Dev environment | `mise.toml` + `pyproject.toml` | Python 3.14, .venv auto-create |

## COMMANDS

```bash
# Install dev dependencies
pip install ".[dev]"

# Run tests with coverage
pytest tests/ --cov=custom_components/electric_ireland_insights --cov-report=term-missing --cov-fail-under=95 -q

# Type checking
mypy custom_components/electric_ireland_insights/ --strict --no-warn-return-any --ignore-missing-imports

# Linting
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/

# Full CI locally (all must pass)
pytest tests/ --cov=custom_components/electric_ireland_insights --cov-fail-under=95 -q && mypy custom_components/electric_ireland_insights/ --strict --no-warn-return-any --ignore-missing-imports && ruff check custom_components/ tests/
```

## CONVENTIONS

- **mypy strict** on all integration code. No `# type: ignore`, no `Any` escape hatches.
- **ruff** for linting + formatting. Config in `pyproject.toml`. Rules: B, E, F, I, S, UP, W, RUF, SIM, T20, ASYNC.
- **pre-commit hooks** for local dev: ruff, mypy, codespell, trailing-whitespace. Config in `.pre-commit-config.yaml`.
- **asyncio_mode = "auto"** in pytest. All test functions are async by default.
- **Coverage omits** `types.py` (TypedDict-only file). All other modules must meet >=95%.
- **No YAML config**. Config-entry-only via `cv.config_entry_only_config_schema(DOMAIN)`.

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER** use `hass.data[DOMAIN]` — use `entry.runtime_data` (Bronze rule: `runtime-data`)
- **NEVER** create sensor entities for energy/cost data — use `async_add_external_statistics` (architectural decision)
- **NEVER** make concurrent API requests to Electric Ireland — sequential day-by-day to avoid rate limiting
- **NEVER** suppress type errors with `# type: ignore`, `cast(Any, ...)`, or `@no_type_check`
- **NEVER** log credentials — use `async_redact_data` for diagnostics
- **NEVER** create new `aiohttp.ClientSession()` — use `async_create_clientsession(hass, ...)`

---

# MANDATORY: HA COMPLIANCE RULES

**Every change to this codebase MUST strictly follow the Home Assistant Integration Quality Scale (IQS) rules, recommended HA architecture, TDD practices, and integration test patterns with minimal mocking.**

The rules below are copied verbatim from the official HA developer documentation and the `script/hassfest/quality_scale.py` source in `home-assistant/core`. Do not edit, reinterpret, or skip any rule.

---

## Integration Quality Scale (IQS) — All 52 Rules

To reach a tier, an integration must fulfill ALL rules of that tier AND all tiers below. Rules may be marked `exempt` with justification in `quality_scale.yaml`.

### BRONZE TIER (18 Rules)

#### 1. action-setup
Register service actions in `async_setup` (not `async_setup_entry`) so automations can be validated even when the config entry is not loaded. Validate inputs inside the action and raise `ServiceValidationError` if invalid.

#### 2. appropriate-polling
Set appropriate polling intervals based on the device/service capabilities. Don't poll too frequently (waste resources) or too infrequently (poor UX). Set `update_interval` in coordinator or `SCAN_INTERVAL` constant.

#### 3. brands
Branding assets must be submitted to the [home-assistant/brands](https://github.com/home-assistant/brands) repository. See the README for icon/logo requirements.

#### 4. common-modules
Place common patterns in standard locations:
- Coordinator in `coordinator.py`
- Base entity in `entity.py`

#### 5. config-flow
Integration must be configurable via the UI:
- Create `config_flow.py`
- Set `config_flow: true` in `manifest.json`
- Store connection config in `ConfigEntry.data`, settings in `ConfigEntry.options`
- Use `data_description` in `strings.json` for context

#### 6. config-flow-test-coverage
100% test coverage for the config flow, including error recovery scenarios. Test happy path, reconfigure, reauthentication, and options flows.

#### 7. dependency-transparency
Dependencies must:
- Have source code available under OSI-approved license
- Be available on PyPI
- Be built/published from public CI pipeline
- Have tagged releases in open online repository

#### 8. docs-actions
Documentation describes all service actions with parameters, descriptions, and whether they are required or optional.

#### 9. docs-high-level-description
Documentation includes high-level description with link to brand/product/service website.

#### 10. docs-installation-instructions
Provide step-by-step installation instructions including any prerequisites.

#### 11. docs-removal-instructions
Provide clear removal instructions.

#### 12. entity-event-setup
Subscribe to events in `async_added_to_hass()`, unsubscribe in `async_will_remove_from_hass()`. Use `self.async_on_remove()` for cleanup callbacks.

#### 13. entity-unique-id
All entities must have a stable `_attr_unique_id` that persists across restarts and is unique across all integrations.

#### 14. has-entity-name
Entities must set `_attr_has_entity_name = True`. Use `_attr_name = None` for the primary feature of a device, resulting in device-name-only entity IDs.

#### 15. runtime-data
Use `entry.runtime_data = coordinator` to store runtime data. Use typed `ConfigEntry[MyType]` for strict typing. Never use `hass.data[DOMAIN][entry.entry_id]`.

#### 16. test-before-configure
Test the connection in the config flow before creating the config entry. Catch DNS, firewall, credential, and device compatibility issues early.

#### 17. test-before-setup
Validate connectivity in `async_setup_entry`. Raise:
- `ConfigEntryNotReady` for temporary issues (HA retries with exponential backoff)
- `ConfigEntryAuthFailed` for auth failures (triggers reauth flow)
- `ConfigEntryError` for permanent configuration errors

#### 18. unique-config-entry
Prevent duplicate configurations via `async_set_unique_id()` + `_abort_if_unique_id_configured()` or `_async_abort_entries_match()`.

### SILVER TIER (10 Rules)

#### 19. action-exceptions
Raise `ServiceValidationError` for usage/input errors. Raise `HomeAssistantError` for service execution failures. Use translatable exception messages.

#### 20. config-entry-unloading
Implement `async_unload_entry` that calls `async_unload_platforms(entry, PLATFORMS)` and cleans up subscriptions, connections, and listeners. Use `entry.async_on_unload()` for callbacks.

#### 21. docs-configuration-parameters
Document all options flow parameters with descriptions.

#### 22. docs-installation-parameters
Document all installation-time parameters with descriptions.

#### 23. entity-unavailable
Mark entities unavailable when device/service is unreachable. Use `unknown` state when data is temporarily missing but connection exists.

#### 24. integration-owner
`codeowners` field in `manifest.json` with GitHub username(s) responsible for maintenance.

#### 25. log-when-unavailable
Log once at `info` level when device becomes unavailable AND once when reconnected. Do not spam logs on every failed poll.

#### 26. parallel-updates
Set `PARALLEL_UPDATES` constant at platform level. Use `0` for coordinator-based read-only platforms (coordinator handles its own locking).

#### 27. reauthentication-flow
Implement `async_step_reauth` + `async_step_reauth_confirm`. Update credentials via `async_update_reload_and_abort`. Users must be able to fix expired credentials without removing/re-adding the integration.

#### 28. test-coverage
Achieve >=95% code coverage across all integration modules.

### GOLD TIER (21 Rules)

#### 29. devices
Set `device_info` on entities with complete `DeviceInfo`: identifiers, name, manufacturer, model, serial number, hw/sw version.

#### 30. diagnostics
Implement `async_get_config_entry_diagnostics`. Redact sensitive information (passwords, tokens, coordinates, account numbers).

#### 31. discovery
Support automatic device discovery via mDNS, Bluetooth, DHCP, SSDP, HomeKit, MQTT, or USB. Declare discovery protocols in `manifest.json`. Mark `exempt` if cloud-only with no local protocol.

#### 32. discovery-update-info
Use discovery info to update IP/host when device is rediscovered (handles DHCP dynamic IPs). Mark `exempt` if no discovery.

#### 33. docs-data-update
Describe how data is updated: polling interval or push mechanism, any limitations (e.g., provider delay).

#### 34. docs-examples
Provide automation blueprints or examples for common use cases.

#### 35. docs-known-limitations
Document known limitations (not bugs). Set proper user expectations.

#### 36. docs-supported-devices
List supported and unsupported devices. Mark `exempt` for service-type integrations.

#### 37. docs-supported-functions
Document all entities, platforms, and functionality provided.

#### 38. docs-troubleshooting
Include troubleshooting section: symptom, description, resolution steps.

#### 39. docs-use-cases
Describe use cases showing the integration's value.

#### 40. dynamic-devices
Auto-create entities for newly discovered devices without reconfiguration. Mark `exempt` for single static device per config entry.

#### 41. entity-category
Set `_attr_entity_category` (`EntityCategory.CONFIG` or `EntityCategory.DIAGNOSTIC`) where appropriate.

#### 42. entity-device-class
Set `_attr_device_class` on entities for proper UI rendering, voice control, unit conversion.

#### 43. entity-disabled-by-default
Set `_attr_entity_registry_enabled_default = False` for noisy or less useful entities.

#### 44. entity-translations
Use `_attr_translation_key` and add translations to `strings.json` under `entity.{platform}.{key}.name`.

#### 45. exception-translations
Use `translation_domain`, `translation_key`, and `translation_placeholders` when raising `HomeAssistantError` or `ServiceValidationError`.

#### 46. icon-translations
Define icons in `icons.json` with support for state-based and range-based icon variants.

#### 47. reconfiguration-flow
Implement `async_step_reconfigure` to allow settings changes without remove/re-add.

#### 48. repair-issues
Use the repair issues system for user-actionable problems. Implement repair flows for automated fixes. Mark `exempt` if only auth failures (handled via reauth).

#### 49. stale-devices
Remove devices when they disappear from hub/account. Implement `async_remove_config_entry_device` for manual removal. Mark `exempt` if no dynamic device lifecycle.

### PLATINUM TIER (3 Rules)

#### 50. async-dependency
Library/dependency must be fully async (asyncio-native). No blocking I/O.

#### 51. inject-websession
Reuse HA's aiohttp session via `async_get_clientsession(hass)` or `async_create_clientsession(hass, ...)`. Dependency must accept a session parameter.

#### 52. strict-typing
Full type hints throughout. mypy strict validation. `py.typed` marker for PEP-561 compliance (if library). Typed `ConfigEntry[MyType]` throughout.

---

## MANDATORY: HA ARCHITECTURE PATTERNS

### Error Handling Hierarchy

| Exception | When | Effect |
|-----------|------|--------|
| `ConfigEntryNotReady` | Temporary network/device failure during setup | HA retries with exponential backoff |
| `ConfigEntryAuthFailed` | Invalid/expired credentials | Triggers reauthentication flow |
| `ConfigEntryError` | Permanent configuration error | Entry fails permanently |
| `UpdateFailed` | Coordinator fetch failure | Entities marked unavailable |
| `ServiceValidationError` | Bad service call parameters | Error shown to user |
| `HomeAssistantError` | Service execution failure | Error shown to user |

### Coordinator Pattern (Required)

```python
class MyCoordinator(DataUpdateCoordinator[MyDataType]):
    config_entry: MyConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MyConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(hours=1))

    async def _async_update_data(self) -> MyDataType:
        try:
            return await self.api.fetch()
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except ConnectionError as err:
            raise UpdateFailed(f"Connection failed: {err}") from err
```

### Runtime Data Pattern (Required)

```python
type MyConfigEntry = ConfigEntry[MyCoordinator]

async def async_setup_entry(hass: HomeAssistant, entry: MyConfigEntry) -> bool:
    coordinator = MyCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator  # NEVER hass.data[DOMAIN]
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

### External Statistics Import Pattern (This Integration)

```python
from homeassistant.components.recorder.statistics import async_add_external_statistics

metadata = StatisticMetaData(
    has_mean=False, has_sum=True,
    name="...", source=DOMAIN,
    statistic_id=f"{DOMAIN}:{unique_id}",
    unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
)
async_add_external_statistics(hass, metadata, statistics)
```

### Entity Pattern (Required)

```python
class MyEntity(CoordinatorEntity[MyCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MyCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{account}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, account)}, name="...", entry_type=DeviceEntryType.SERVICE)
```

### Config Flow Pattern (Required)

```python
class MyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate(user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="...", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
```

### Session Management (Platinum Requirement)

```python
from homeassistant.helpers.aiohttp_client import async_create_clientsession

# CORRECT: Reuse HA's session infrastructure
session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())

# NEVER: Create standalone sessions
session = aiohttp.ClientSession()  # FORBIDDEN
```

---

## MANDATORY: TDD WORKFLOW

### For Every Code Change

1. **RED**: Write a failing test FIRST that captures the expected behavior
2. **GREEN**: Write the minimal code to make the test pass
3. **REFACTOR**: Clean up while keeping tests green
4. **VERIFY**: Run full suite + mypy — both must pass

### Test Requirements

- **Coverage**: >=95% on all modules (CI enforces `--cov-fail-under=95`)
- **Async**: All tests are async (`asyncio_mode = "auto"`)
- **Minimal mocking**: Mock only external boundaries (HTTP responses via `aioresponses`, HA internals via `pytest-homeassistant-custom-component`). Never mock internal logic.
- **Config flow**: 100% path coverage including every error branch
- **Coordinator**: Test success, auth failure, connection failure, data transformation
- **Entities**: Test native_value, unique_id, device_info, entity_category

### What to Mock vs What to Test Real

| Mock (external boundary) | Test real (internal logic) |
|--------------------------|---------------------------|
| HTTP responses (`aioresponses`) | HTML parsing logic |
| HA recorder (`recorder_mock`) | Statistics calculation |
| Config entries (`MockConfigEntry`) | Config flow validation logic |
| Time (`freezegun` / `async_fire_time_changed`) | Coordinator update logic |

### Running Tests

```bash
# Full suite with coverage (must pass before any PR)
pytest tests/ --cov=custom_components/electric_ireland_insights --cov-report=term-missing --cov-fail-under=95 -q

# Single test file
pytest tests/test_coordinator.py -v

# Single test
pytest tests/test_coordinator.py::test_specific_function -v
```

---

## MANDATORY: QUALITY GATE

Before any change is considered complete:

1. `pytest tests/ --cov-fail-under=95` passes
2. `mypy --strict` passes with zero errors
3. `ruff check` and `ruff format --check` pass with zero errors
4. `quality_scale.yaml` updated if new rules are satisfied or new exemptions needed
5. `docs/index.md` updated if user-facing behavior changes
6. `strings.json` updated if new UI strings, errors, or entity names added
7. No regressions in existing tests

---

## REFERENCE INTEGRATIONS

| Integration | Tier | Why Study It |
|-------------|------|-------------|
| **[Opower](https://github.com/home-assistant/core/tree/dev/homeassistant/components/opower)** | Platinum | Primary reference: `async_add_external_statistics`, cloud polling, cookie-based auth |
| **[Shelly](https://github.com/home-assistant/core/tree/dev/homeassistant/components/shelly)** | Platinum | Complex multi-platform, complete `quality_scale.yaml` |
| **[ista_ecotrend](https://github.com/home-assistant/core/tree/dev/homeassistant/components/ista_ecotrend)** | Gold | Simpler external statistics pattern |
| **[Rainbird](https://github.com/home-assistant/core/tree/dev/homeassistant/components/rainbird)** | Platinum | HTTP polling with connection limits |

## NOTES

- Electric Ireland data arrives with 1-3 day delay from ESB. The coordinator uses a lookback window (30 days initial, 7 days subsequent) to catch late-arriving data.
- The integration scrapes HTML (no official API). Login mimics browser interaction with CSRF tokens. This is fragile — website changes can break the integration.
- `beautifulsoup4` is the only external dependency. All HTTP goes through HA's aiohttp infrastructure.
- Statistics use cumulative sum with overlap detection to maintain recorder continuity.
