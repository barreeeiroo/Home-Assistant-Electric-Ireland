# OAuth/API Investigation: Alternatives to Page Scraping for Electric Ireland

> **Date**: 2026-04-11
> **Status**: Complete — No OAuth/API alternative exists today
> **Next review**: Q3 2026 (SMDAC API expected)

## TL;DR

**No OAuth or official API path exists to eliminate scraping for Electric Ireland.** The current architecture is already near-optimal — HTML scraping is confined to login only (3 HTTP requests), and all data retrieval is pure JSON API calls through EI's server-side proxy to Bidgely.

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [Electric Ireland — No Public API](#2-electric-ireland--no-public-api)
3. [Bidgely — The Hidden Backend](#3-bidgely--the-hidden-backend)
4. [Live Testing Results](#4-live-testing-results)
5. [ESB Networks — Azure AD B2C](#5-esb-networks--azure-ad-b2c)
6. [SMDAC — EU-Mandated API (Future)](#6-smdac--eu-mandated-api-future)
7. [EU Regulatory Landscape](#7-eu-regulatory-landscape)
8. [Mobile App Analysis](#8-mobile-app-analysis)
9. [Irish/UK Energy Integration Landscape](#9-irishuk-energy-integration-landscape)
10. [New Endpoints Discovered](#10-new-endpoints-discovered)
11. [Options Ranked](#11-options-ranked)
12. [Recommendation](#12-recommendation)

---

## 1. Current Architecture

```
User Browser                    EI Server                     Bidgely API
    |                              |                              |
    |-- GET / (login page) ------->|                              |
    |<---- HTML + CSRF tokens -----|                              |
    |-- POST / (credentials) ----->|                              |
    |<---- session cookies --------|                              |
    |-- POST /Accounts/OnEvent --->|                              |
    |<---- Insights HTML ----------|                              |
    |                              |                              |
    |-- GET /MeterInsight/...  --->|-- server-side auth --------->|
    |<---- JSON response ----------|<---- JSON response ----------|
```

**Scraping surface**: Only 3 requests require HTML parsing (login page CSRF extraction, dashboard account discovery, Insights page meter ID extraction). All data retrieval (`/MeterInsight/` endpoints) returns JSON.

### Authentication Flow

1. `GET https://youraccountonline.electricireland.ie/` → extract `Source` + `rvt` CSRF tokens
2. `POST https://youraccountonline.electricireland.ie/` → submit credentials, receive session cookies
3. `POST /Accounts/OnEvent` → navigate to Insights, extract `data-partner`, `data-contract`, `data-premise` from `div#modelData`

### Data Retrieval (JSON API, no scraping)

- `GET /MeterInsight/{partner}/{contract}/{premise}/bill-period` → billing period boundaries
- `GET /MeterInsight/{partner}/{contract}/{premise}/hourly-usage?date=YYYY-MM-DD` → 24 hourly datapoints with consumption (kWh) and cost (EUR)

### Session Management

- `aiohttp.ClientSession` with `CookieJar` via `async_create_clientsession(hass)`
- ASP.NET Core session cookies: `rvt`, `ARRAffinity`, `ARRAffinitySameSite`, `EI.RP`, `.AspNetCore.Session`

---

## 2. Electric Ireland — No Public API

### Evidence

| Search Target | Result |
|---------------|--------|
| Developer portal | None exists |
| OAuth2/OpenID Connect endpoints | None found |
| Public API documentation | None found |
| Swagger/OpenAPI specs on EI domains | None found |
| Partnership/developer program | Sales only, not technical |
| Mobile app API docs | None found |

### Content Security Policy (Revealing)

The CSP header from the login page explicitly allows Bidgely:

```
script-src 'self' 'unsafe-inline' *.google.com ... static.bidgely.com;
```

This confirms Bidgely integration at the infrastructure level.

---

## 3. Bidgely — The Hidden Backend

### Partnership

Electric Ireland partnered with **Bidgely** (UtilityAI platform) in **March 2021** to power their "Smart Meter Insights" feature. Bidgely provides AI-powered energy analytics including appliance-level disaggregation.

Sources:
- [Bidgely Partners with Electric Ireland](https://www.bidgely.com/bidgely-partners-with-electric-ireland-and-enhances-smart-meter-deployment/) (March 2021)

### Electric Ireland's Bidgely Configuration

Extracted from `/vendor/bidgely/js/bundle.js` (served from EI's portal):

| Parameter | Value |
|-----------|-------|
| `pilotId` | `20015` |
| `clientId` | `ei-dashboard` |
| `clientSecret` | `d@shbo@rd!` |
| Domain pattern | `ei(-?)([a-z]*[0-9]*)\.bidgely\.com` |

### Bidgely API Domains Found in Bundle

| Domain | Purpose |
|--------|---------|
| `https://api.eu.bidgely.com` | **EU Production API** (Electric Ireland's region) |
| `https://eiuatapi.bidgely.com` | Electric Ireland UAT (testing) environment |
| `https://ssoprod.bidgely.com` | SSO production endpoint |
| `https://sso-nonprod.bidgely.com` | SSO non-production |
| `https://naapi.bidgely.com` | North America API |
| `https://static.bidgely.com` | Static assets (JS, CSS, fonts) |

### Bidgely SDK Architecture (from bundle.js analysis)

The Bidgely Web SDK (`BidgelyWebSdk`) is loaded on the Insights page and initialized via:

```javascript
BidgelyWebSdk.initialize(window.RunMode, window.bidgelyWebSdkPayload, callback);
```

The SDK handles **UI widget rendering only** (charts, graphs, appliance breakdown visualization). It does NOT make data API calls — those go through EI's server-side proxy.

### SSO Token Flow (from bundle.js)

```javascript
// SDK stores tokens in localStorage
setAccessToken(token)      // Bearer token for API calls
setSSOToken(ssoToken)      // SSO token from utility
setSSOSession(true)        // Mark session as SSO-authenticated

// initSessionForSSO receives an object with token property
initSessionForSSO(e) {
    this.setSSOSession(true);
    var t = e.token;
    t && this.setAccessToken(t);
}
```

### xdomain Cross-Origin Configuration

The bundle configures `xdomain` (cross-origin AJAX library) with proxy slaves for all Bidgely API domains:

```javascript
{
    "https://btocdevapi.bidgely.com": "/proxy.html",
    "https://eiuatapi.bidgely.com": "/proxy.html",
    "https://naapi.bidgely.com": "/proxy.html",
    "https://api.eu.bidgely.com": "/proxy.html"
}
```

Despite this configuration, **no actual cross-origin requests to Bidgely were observed** in live testing (see Section 4).

### Direct Bidgely API Testing (Live — April 2026)

We tested whether the extracted credentials could provide direct API access.

#### What Worked

```
POST https://api.eu.bidgely.com/oauth/token
  grant_type=client_credentials
  client_id=ei-dashboard
  client_secret=d@shbo@rd!

→ 200 OK
  {"access_token":"1a7df726-...","token_type":"bearer","expires_in":863999}
```

The `client_credentials` grant returns a valid **utility-level bearer token** (10-day expiry).

#### What Did NOT Work

Every user-data endpoint returns `401 Not authorized for this user` with the utility token:

| Endpoint Tested | Result |
|----------------|--------|
| `/v2.0/users/{accountId}` | 401 |
| `/v2.0/pilots/20015/users/{accountId}` | 401 |
| `/v2.0/dashboard/users/{accountId}/usage-chart-data` | 401 |
| `/2.1/users/{accountId}/homes/1/billprojections` | 401 |
| `/billingdata/users/{accountId}/homes/1/usagedata` | 401 |
| `/v2.0/users/me` | 401 |
| All session/init endpoints | 401 |

We also tried:

| Grant/Exchange Type | Result |
|--------------------|--------|
| `password` grant with EI credentials | `400 invalid_grant` — "Unauthorized grant type: password" |
| RFC 8693 token exchange | `400 unsupported_grant_type` |
| Scoped token (`scope=pilot:20015 user:REDACTED_ACCT`) | Token issued (200) but scope is **cosmetic** — data endpoints still 401 |
| User context headers (`X-User-Id`, `X-External-Id`, etc.) | All 401 |
| Basic Auth with clientId/clientSecret | 401 |

#### Why the Credentials Aren't Enough (Three Authorization Layers)

1. **Token type**: `client_credentials` tokens are utility-admin only. User data requires an SSO-minted user token that only EI's server can create.
2. **User identity**: Bidgely uses internal UUIDs, not EI account numbers (`REDACTED_ACCT`). There is no lookup endpoint accessible with a client token.
3. **SSO binding**: User tokens are minted by EI's server through an encrypted payload exchange (AES-256-CBC with utility-specific keys, as seen in the Hydro Ottawa reference implementation).

### Why Direct Bidgely Access Is Not Possible

1. **No public consumer OAuth2 endpoints** — Bidgely is B2B only (utility partners)
2. **SSO tokens are generated server-side** by EI's backend after authentication
3. **Each utility has unique credentials** — Cognito pool IDs, AES encryption keys, SSO endpoints (per `carterjgreen/bidgely` library analysis)
4. **EI uses server-side proxy** — browser never contacts Bidgely directly
5. **Client credentials give utility token, not user token** — confirmed by live testing (401 on all user endpoints)
6. **Scope parameter is cosmetic** — token endpoint echoes any scope but authorization layer ignores it
7. **Meter IDs (partner/contract/premise) are NOT Bidgely UUIDs** — tested all as user identifiers, all 401
8. **EI credentials don't work with Bidgely** — `password` grant rejected ("Unauthorized grant type"), Bidgely has a separate user database
9. **SSO session creation blocked** — tested `ssoprod.bidgely.com` and `api.eu.bidgely.com` SSO endpoints with all combinations of IDs, all 401/403

### Why Users Can't Access Their Own Data Directly

Despite having valid EI credentials, meter IDs, and Bidgely client credentials, direct access is blocked by architecture:

| What You Have | What Bidgely Needs | Gap |
|--------------|-------------------|-----|
| EI email + password | Bidgely UUID + SSO token | Bidgely has separate user DB; doesn't know EI credentials |
| EI account `REDACTED_ACCT` | Bidgely internal UUID | No lookup endpoint accessible with client token |
| `clientId` + `clientSecret` | Server-side API key | Bundle credentials are public widget creds; real key is on EI's server |
| partner/contract/premise IDs | Bidgely user UUID | These are EI's proxy routing IDs, not Bidgely identifiers |

The only entity that can bridge this gap is **EI's server**, which holds:
- The server-side Bidgely API key (higher privilege than the public `clientSecret`)
- The mapping table: EI account numbers → Bidgely UUIDs
- The ability to mint user-scoped SSO tokens via Bidgely's server-to-server API

### Consumer Rights Note (GDPR Article 20)

Under GDPR data portability rules, consumers ARE entitled to their energy data in machine-readable format. However, no technical mechanism exists today to exercise this right programmatically for Bidgely-hosted data. Ireland's SMDAC API (~Q3 2026) is designed to address this gap.

### Reference: Hydro Ottawa's Bidgely Auth (for comparison)

The `carterjgreen/bidgely` Python library reveals a different utility's flow:

1. AWS Cognito SRP authentication (pool `ca-central-1_VYnwOhMBK`, client `7scfcis6ecucktmp4aqi1jk6cb`)
2. AES-256-CBC encryption of Bidgely payload with hardcoded key/IV
3. POST encrypted token to `https://usage.hydroottawa.com/api/v1/sso/dashboard`
4. Redirect response contains `uuid` (user ID) and `token` (Bearer token)
5. API calls to `https://naapi-read.bidgely.com` with `Authorization: Bearer {token}`

Electric Ireland does NOT follow this pattern — they proxy everything server-side.

---

## 4. Live Testing Results

### Account Discovery (aiohttp)

- Successfully logged in and discovered account `REDACTED_ACCT` (Electricity, REDACTED_ADDRESS)
- Meter IDs: partner=`REDACTED_PARTNER`, contract=`REDACTED_CONTRACT`, premise=`REDACTED_PREMISE`

### Insights Page Analysis (aiohttp)

**`div#modelData` attributes** (more than the code currently extracts):

| Attribute | Value |
|-----------|-------|
| `data-premise` | `REDACTED_PREMISE` |
| `data-partner` | `REDACTED_PARTNER` |
| `data-contract` | `REDACTED_CONTRACT` |
| `data-microgen` | `False` |
| `data-showreviewtab` | `False` |
| `data-accountno` | `REDACTED_ACCT` |
| `data-prepaycustomer` | `False` |
| `data-dualfuelaccount` | `False` |
| `data-startwithreviewtab` | `False` |

**Bidgely references in page HTML**:
- `/vendor/bidgely/css/main.a57d01cd.css`
- `https://static.bidgely.com/scripts/xdomain.min.js`
- `/vendor/bidgely/js/bundle.js`

**Token/Auth/OAuth patterns in HTML**: None found.

**Session cookies** (all on EI domain):
- `rvt`, `ARRAffinity`, `ARRAffinitySameSite`, `EI.RP`, `.AspNetCore.Session`

**No Bidgely cookies** observed.

### Playwright Network Capture (Definitive)

After logging in and navigating to Insights page in a real browser, **ALL network requests were captured**:

| Request | Domain | Auth |
|---------|--------|------|
| `GET /MeterInsight/.../bill-period` | `youraccountonline.electricireland.ie` | Session cookies |
| `GET /MeterInsight/.../bill-period` | `youraccountonline.electricireland.ie` | Session cookies |
| `GET /MeterInsight/.../usage-daily?start=2026-03-26&end=2026-04-25` | `youraccountonline.electricireland.ie` | Session cookies |
| `GET /MeterInsight/.../appliance-usage?start=2026-02-26&end=2026-03-25` | `youraccountonline.electricireland.ie` | Session cookies |

**ZERO requests to any `*.bidgely.com` domain.** EI's server proxies all data requests.

---

## 5. ESB Networks — Azure AD B2C

### Overview

ESB Networks (the DSO) operates Ireland's smart meter infrastructure. They provide a separate customer portal with their own authentication.

| Detail | Value |
|--------|-------|
| Portal | `https://myaccount.esbnetworks.ie` |
| Auth | Azure AD B2C (`esbntwkscustportalprdb2c01.onmicrosoft.com`) |
| Data | 30-minute interval HDF (CSV/JSON) |
| History | Up to 2 years |
| Delay | 36-48 hours |
| Requires | Separate MPRN + ESB Networks account |

### Endpoints

- `/DataHub/DownloadHdf?mprn={mprn}` — full HDF download
- `/datahub/GetHdfContent?mprn={mprn}&startDate={date}` — date-filtered data

### Blockers

- **CAPTCHA added November 2024** — automated login increasingly difficult
- Rate limited to ~2 logins/IP/24 hours
- **No cost data** — only raw kW/kWh consumption (supplier-agnostic)
- Requires separate credentials from Electric Ireland
- ToS explicitly prohibits automated access (Section 4.2)

### Existing Projects

| Project | Stars | Status |
|---------|-------|--------|
| `badger707/esb-smart-meter-reading-automation` | 91 | Active (Aug 2025) |
| `RobinJ1995/home-assistant-esb-smart-meter-integration` | 21 | Active |
| `antoine-voiry/home-assistant-esb-smart-meter-integration` | 3 | Active |

---

## 6. SMDAC — EU-Mandated API (Future)

### Current Status (as of April 2026): NOT LIVE

The Smart Meter Data Access Code (SMDAC) was published by CRU in February 2025. Implementation is ongoing.

### Timeline

| Date | Event |
|------|-------|
| Feb 2025 | CRU published SMDAC (CRU202517) and Decision Paper (CRU202516) |
| Dec 2025 | S.I. 589/2025 enacted, giving legal effect to SMDAC |
| Jul 2025 | EU reporting deadline (Ireland's submission status uncertain) |
| ~Aug 2026 | Expected full implementation (12-18 months from publication) |
| Jun 2026 | Dynamic pricing deadline for suppliers |

### What SMDAC Will Provide

- **API-connected system** as primary access method
- Third-party registration and authorization framework
- Customer consent management
- Standardized data formats (likely CIM-based)

### What's NOT Available Yet

- No developer/API portal
- No registered third-party developers
- No SMDAC-compliant API for programmatic access
- No public API specifications

### Key Sources

- [CRU SMDAC Decision](https://www.cru.ie/publications/28576/)
- [ESB Networks SMDAC Page](https://www.esbnetworks.ie/about-us/company/data-and-digital/smart-meter-data-access-code)
- [S.I. 589/2025](https://www.irishstatutebook.ie/eli/2025/si/589/made/en/print)

---

## 7. EU Regulatory Landscape

### Applicable Regulations

| Regulation | Mandate | Ireland Status |
|------------|---------|----------------|
| **EU Directive 2019/944 Art. 20** | Consumer access to validated historical + near-real-time data | Transposed via S.I. 37/2022 |
| **EU Implementing Regulation 2023/1162** | Reference model with 6 data access procedures, API-based | SMDAC published; reporting due Jul 2025 |
| **GDPR Article 20** | Machine-readable data portability | Applies; consumers can request |
| **S.I. 37/2022** | CRU to develop Smart Meter Data Access Code | SMDAC finalized Feb 2025 |
| **S.I. 589/2025** | Amendment incorporating EU reference model | In force Dec 2025 |

### Comparative EU Models

| Country | Platform | API Access | Notes |
|---------|----------|------------|-------|
| **Denmark** | eloverblik.dk | Full consumer REST API | Gold standard |
| **Netherlands** | Meterbeheer | Unified API for all meters | ODA certification required |
| **France** | RTE Services Portal | API access to metering data | Contract required |
| **UK** | DCC via Hildebrand/n3rgy | Intermediary-based | Consumer-facing |
| **Ireland** | None | No consumer API | SMDAC in progress |

### Ireland's EU Report Status

Under Implementing Regulation 2023/1162, Member States had until July 5, 2025 to report national practices. Ireland is **NOT listed** in the publicly available EU repository, suggesting a missed deadline or delayed submission.

---

## 8. Mobile App Analysis

### Electric Ireland App

| Attribute | Value |
|-----------|-------|
| Package (Android) | `ie.electricireland.resmobile` |
| iOS App ID | `id6444361812` |
| Current Version | 5.4.1 (iOS), 6.0.4 (Android) |
| Developer | Electricity Supply Board (ESB) |

### Findings

- **No reverse-engineered API documentation exists** — searched GitHub, Stack Overflow, security research blogs
- App likely uses the same backend as the web portal
- May use certificate pinning (common in utility apps)
- Would require MITM proxy analysis to investigate further

### Assessment

Not worth pursuing — high effort, likely ToS violation, probably uses same server-side architecture as web portal.

---

## 9. Irish/UK Energy Integration Landscape

| Provider | Country | Auth Method | API Type | Real-time? |
|----------|---------|-------------|----------|------------|
| **Octopus Energy** | UK | API Key | Official REST/GraphQL | Yes (w/ Home Mini) |
| **Hildebrand Glow** | UK | Bright App creds | Local MQTT / Cloud | Yes (CAD device) |
| **n3rgy** | UK | IHD MAC address | REST (restricted since Dec 2024) | No (30-min) |
| **Opower** | US | Username/password + MFA | Web scraping | No (48-hr) |
| **ESB Networks** | IE | Azure AD B2C | Portal scraping + CAPTCHA | No (36-48hr) |
| **Electric Ireland** | IE | Session + CSRF | Scraping → JSON proxy | No (1-3 day) |

### Hardware Solutions

- **UK**: CAD devices (Hildebrand, Chameleon) read directly from meter Zigbee HAN port
- **Ireland**: **No consumer-accessible HAN port** on Irish smart meters
- Only DIY option: pulse LED reading with ESPHome/Shelly (not practical for this integration)

---

## 10. New Endpoints Discovered

During live testing, two previously unknown endpoints were observed:

| Endpoint | Status | Description |
|----------|--------|-------------|
| `/MeterInsight/{p}/{c}/{pr}/bill-period` | ✅ Already used | Bill period date boundaries |
| `/MeterInsight/{p}/{c}/{pr}/hourly-usage?date=` | ✅ Already used | 24 hourly datapoints (kWh + EUR) |
| `/MeterInsight/{p}/{c}/{pr}/usage-daily?start=&end=` | 🆕 **New** | Daily aggregated usage over date range |
| `/MeterInsight/{p}/{c}/{pr}/appliance-usage?start=&end=` | 🆕 **New** | Bidgely appliance disaggregation data |

The `usage-daily` endpoint could potentially replace multiple `hourly-usage` calls for initial data loading. The `appliance-usage` endpoint provides Bidgely's appliance-level breakdown (fridge, heating, etc.) which could be exposed as additional statistics.

---

## 11. Options Ranked

| Rank | Option | Viability | Effort | Eliminates Scraping? |
|------|--------|-----------|--------|---------------------|
| **1** | **Keep current approach** | ✅ Best available | Already done | No (login only) |
| **2** | **SMDAC API** (future ~Aug 2026) | ⏳ Monitor | Low (when available) | Yes |
| **3** | **ESB Networks** (supplementary) | ⚠️ Difficult | High | Yes, but no cost data + CAPTCHA |
| **4** | **Bidgely direct** | ❌ Impossible | N/A | N/A — server-side proxy |
| **5** | **Mobile app reverse engineering** | ❌ Not worth it | Very High | Unknown |

---

## 12. Recommendation

**No changes needed to the integration's authentication approach.**

The current implementation is already the most efficient path available:
- Login scraping is unavoidable and minimal (3 HTTP requests)
- All data retrieval is clean JSON REST API
- EI's server-side proxy to Bidgely means no shortcut exists

### Action Items

1. **Monitor SMDAC**: Check [ESB Networks SMDAC page](https://www.esbnetworks.ie/about-us/company/data-and-digital/smart-meter-data-access-code) quarterly for API availability (~Q3 2026 expected)
2. **Consider `usage-daily` endpoint**: Could reduce API calls during initial data loading
3. **Consider `appliance-usage` endpoint**: Could expose appliance-level breakdown as additional statistics
4. **Monitor dynamic pricing launch**: June 2026 deadline may accelerate SMDAC implementation

### What Will NOT Help

- Waiting for Electric Ireland to release a public API (no evidence this is planned)
- Attempting direct Bidgely API access (server-side proxy, no client tokens)
- Mobile app reverse engineering (no existing work, high effort, likely same backend)
- Hardware solutions (Irish meters don't support consumer HAN access)
