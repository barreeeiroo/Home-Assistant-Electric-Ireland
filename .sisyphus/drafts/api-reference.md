# Electric Ireland Mobile App — API Reference (from MITM Capture)

> All values sanitized. Real credentials, tokens, and PII replaced with realistic fakes.
> Captured 2026-04-06 via WiFi AP MITM proxy intercepting iOS app traffic.

---

## Authentication: Azure AD B2C OAuth2 PKCE

### OpenID Configuration
```
GET https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/B2C_1A_SIGNIN/v2.0/.well-known/openid-configuration
```
```json
{
  "issuer": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/v2.0/",
  "authorization_endpoint": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/authorize",
  "token_endpoint": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/token",
  "end_session_endpoint": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/logout",
  "jwks_uri": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/discovery/v2.0/keys",
  "response_types_supported": ["code", "code id_token", "code token", "code id_token token", "id_token", "id_token token", "token", "token id_token"],
  "scopes_supported": ["openid"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
  "claims_supported": ["sub", "email", "oid", "EI.RP.Cookie", "correlationId", "iss", "iat", "exp", "aud", "acr", "nonce", "auth_time"]
}
```

### Step 1: Authorize (GET — returns login HTML page)
```
GET https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/authorize
  ?code_challenge={S256_HASH}
  &code_challenge_method=S256
  &redirect_uri=eiresmobile://signin-oidc
  &client_id=945ebf3e-5eaa-4165-9e3f-81e70ab727ba
  &response_type=code
  &state={RANDOM_STATE}
  &scope=openid offline_access https://eiresmarketsb2cprd01.onmicrosoft.com/1c027503-5ff2-42c7-a6ac-0f72bf386c82/API.Access
```

Response: HTML page containing:
- Cookie `x-ms-cpim-csrf` (CSRF token)
- JavaScript var `SETTINGS` with `csrf` field
- Form fields: `signInName` (email), `password`

### Step 2: SelfAsserted (POST — submit credentials)
```
POST https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/B2C_1A_Signin/SelfAsserted
  ?tx=StateProperties={BASE64_STATE}
  &p=B2C_1A_Signin

Headers (ALL are required — missing any causes AADB2C policy exception):
  Host: id.electricireland.ie
  Accept: application/json, text/javascript, */*; q=0.01
  Content-Type: application/x-www-form-urlencoded; charset=UTF-8
  X-CSRF-TOKEN: {CSRF_TOKEN_FROM_COOKIE}
  X-Requested-With: XMLHttpRequest
  Sec-Fetch-Site: same-origin
  Sec-Fetch-Mode: cors
  Sec-Fetch-Dest: empty
  Origin: https://id.electricireland.ie
  Referer: {AUTHORIZE_URL}
  User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.4 Mobile/15E148 Safari/604.1
  Cookie: x-ms-cpim-cache|{SESSION_KEY}={CACHE_VALUE}; x-ms-cpim-csrf={CSRF_TOKEN}; x-ms-cpim-trans={TRANS_TOKEN}

Body:
  request_type=RESPONSE&signInName={EMAIL}&password={PASSWORD}
```

**CRITICAL**: The request MUST include:
- All three `x-ms-cpim-*` cookies from the authorize response (cache, csrf, trans)
- The `X-CSRF-TOKEN` header matching the `x-ms-cpim-csrf` cookie value
- The `Origin` and `Referer` headers (B2C validates these)
- The `X-Requested-With: XMLHttpRequest` header
- The `tx=StateProperties={BASE64_STATE}` query param from the authorize step

Without any of these, B2C returns `AADB2C: An exception has occurred` with no detail.

### Step 3: Confirmed (GET — get authorization code)
```
GET https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/B2C_1A_Signin/api/CombinedSigninAndSignup/confirmed
  ?rememberMe=false
  &csrf_token={CSRF_TOKEN}
  &tx=StateProperties={BASE64_STATE}
  &p=B2C_1A_Signin

Headers:
  Cookie: x-ms-cpim-csrf={CSRF_TOKEN}
```

Response: HTML/redirect containing authorization `code` in the redirect URL:
`eiresmobile://signin-oidc?code={AUTH_CODE}&state={STATE}`

### Step 4: Token Exchange (POST — get access + refresh tokens)
```
POST https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/token

Body (form-encoded):
  grant_type=authorization_code
  &client_id=945ebf3e-5eaa-4165-9e3f-81e70ab727ba
  &code_verifier={PKCE_VERIFIER_128_CHARS}
  &redirect_uri=eiresmobile://signin-oidc
  &code={AUTH_CODE}
```

Response:
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiI...(JWT)",
  "token_type": "Bearer",
  "expires_in": 300,
  "refresh_token": "eyJraWQiOiJDYzBZaWhm...(opaque)",
  "id_token": "eyJhbGciOiJSUzI1NiI...(JWT)"
}
```

Access token JWT claims:
```json
{
  "aud": "1c027503-5ff2-42c7-a6ac-0f72bf386c82",
  "iss": "https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/v2.0/",
  "exp": 1775481695,
  "sub": "user@example.com",
  "email": "user@example.com",
  "EI.RP.Cookie": "...(encrypted)",
  "oid": "9119314f-3498-4746-8af4-714dc82bae44",
  "scp": "API.Access",
  "azp": "945ebf3e-5eaa-4165-9e3f-81e70ab727ba"
}
```

### Token Refresh
```
POST https://id.electricireland.ie/0efed6cc-a0f6-4340-9909-5377f6e31706/b2c_1a_signin/oauth2/v2.0/token

Body (form-encoded):
  grant_type=refresh_token
  &client_id=945ebf3e-5eaa-4165-9e3f-81e70ab727ba
  &refresh_token={REFRESH_TOKEN}
```

---

## REST API: api.esb.ie

### Common Headers (every request)
```
User-Agent: ElectricIreland/150550 CFNetwork/3860.500.112 Darwin/25.4.0
Authorization: Bearer {ACCESS_TOKEN}    (authenticated endpoints only)
```

**TWO different API subscription keys** (different API Management gateways):
```
Portal endpoints (/ei/residential-portal-roi*/):
  api-subscription-key: 1d5c129fdff94950a5f783b4c181adef

MeterInsight endpoints (/ei/res-market-hub/v1.0/api/MeterInsight/):
  api-subscription-key: 3b7f0b13d1364088be0dbbfc054b3186
```

### GET /ei/residential-portal-roi-auth/v1.0/VersionCheck (no auth)
```
POST https://api.esb.ie/ei/residential-portal-roi-auth/v1.0/VersionCheck
Content-Type: application/json

{"application":"ei-resmobile","platform":"ios","currentVersion":"6.2.2","osVersion":"26.4"}
```
```json
{"minimumVersion":"5.0.1","latestVersion":"5.0.1","updateRequired":false,"updateAvailable":false,"message":null}
```

### GET /ei/residential-portal-roi-auth/v1.0/Outages (no auth)
```json
{"currentOutage":false,"scheduledOutage":false,"startDateTime":null,"endDateTime":null}
```

### GET /ei/residential-portal-roi/v1.0/Accounts (auth required)
```json
[
  {
    "partner": "PARTNER_001",
    "accountNumber": "100000001",
    "contractId": "CONTRACT_001",
    "premiseId": "PREMISE_001",
    "accountAddress": "123 SAMPLE STREET, DUBLIN",
    "clientAccountType": 1,
    "isPayAsYouGo": false,
    "isSmartPrepay": false,
    "preventMeterReading": true,
    "isMicrogen": false
  }
]
```

### GET /ei/residential-portal-roi/v1.0/Accounts/{accountNumber} (auth required)
```json
{
  "accountNumber": "100000001",
  "accountClosed": false,
  "hasStaffDiscountApplied": false,
  "amountDue": 0.0,
  "isDue": false,
  "dueDate": null,
  "overduePayments": [],
  "paymentMethod": 2,
  "IBAN": "******************0000",
  "nameInBankAccount": "SAMPLE NAME",
  "billing": {
    "latestBillDate": "2026-03-27",
    "dueDate": "2026-04-10",
    "nextBillDate": "2026-04-25",
    "hasAccountCredit": false,
    "isDue": false,
    "isOverDue": false,
    "canPayNow": true,
    "hasAlternativePayer": false,
    "billingDayOfMonth": null,
    "equalizerAmount": null
  },
  "smartActivationStatus": 4,
  "showSmartUpgradeBanner": false
}
```

### GET /ei/residential-portal-roi/v1.0/UserDetails (auth required)
```json
[
  {
    "partnerId": "PARTNER_001",
    "userDetails": {
      "contactEmail": "user@example.com",
      "primaryPhoneNumber": "0831234567",
      "alternativePhoneNumber": "",
      "loginEmail": "USER@EXAMPLE.COM",
      "addressLines": "123 SAMPLE STREET, DUBLIN"
    },
    "marketingPreferences": {
      "smsMarketingActive": false,
      "doorToDoorMarketingActive": false,
      "landLineMarketingActive": false,
      "postMarketingActive": false,
      "emailMarketingActive": false,
      "mobileMarketingActive": false,
      "emailPreferenceUpdatedOneYearBefore": false
    }
  }
]
```

### GET .../MeterInsight/{partner}/{contract}/{premise}/hourly-usage?date=YYYY-MM-DD (auth required)

URL: `https://api.esb.ie/ei/res-market-hub/v1.0/api/MeterInsight/{partnerId}/{contractId}/{premiseId}/hourly-usage?date=2026-04-04`

```json
{
  "subStatusCode": "SUCCESS",
  "message": "Successfully executed query for query Uasge hourly",
  "data": [
    {
      "startDate": "2026-04-03T23:00:00Z",
      "endDate": "2026-04-03T23:59:59Z",
      "midPeak": null,
      "offPeak": {"cost": 0.82, "consumption": 4.197},
      "onPeak": null,
      "flatRate": null,
      "categories": null
    },
    {
      "startDate": "2026-04-04T07:00:00Z",
      "endDate": "2026-04-04T07:59:59Z",
      "midPeak": {"cost": 0.46, "consumption": 1.246},
      "offPeak": null,
      "onPeak": null,
      "flatRate": null,
      "categories": null
    },
    {
      "startDate": "2026-04-04T16:00:00Z",
      "endDate": "2026-04-04T16:59:59Z",
      "midPeak": null,
      "offPeak": null,
      "onPeak": {"cost": 0.06, "consumption": 0.16},
      "flatRate": null,
      "categories": null
    }
  ],
  "isSuccess": true
}
```

Note: Each hour has exactly ONE of midPeak/offPeak/onPeak populated (the others are null). The active bucket depends on the time-of-use tariff schedule.

### GET .../MeterInsight/{partner}/{contract}/{premise}/usage-daily?start=YYYY-MM-DD&end=YYYY-MM-DD (auth required)

```json
{
  "subStatusCode": "SUCCESS",
  "message": "Successfully executed query for query Uasge daily",
  "data": [
    {
      "startDate": "2026-03-26T00:00:00Z",
      "endDate": "2026-03-26T23:59:59Z",
      "midPeak": {"cost": 9.24, "consumption": 24.951},
      "offPeak": {"cost": 1.71, "consumption": 8.808},
      "onPeak": {"cost": 1.2, "consumption": 3.048},
      "flatRate": null,
      "categories": null
    },
    {
      "startDate": "2026-03-27T00:00:00Z",
      "endDate": "2026-03-27T23:59:59Z",
      "midPeak": {"cost": 7.33, "consumption": 19.798},
      "offPeak": {"cost": 1.55, "consumption": 7.984},
      "onPeak": {"cost": 0.63, "consumption": 1.584},
      "flatRate": null,
      "categories": null
    }
  ],
  "isSuccess": true
}
```

### GET .../MeterInsight/{partner}/{contract}/{premise}/usage?year=YYYY (auth required)

```json
{
  "subStatusCode": "SUCCESS",
  "message": "Successfully executed query for query Uasge",
  "data": [
    {
      "startDate": "2025-12-26T00:00:00Z",
      "endDate": "2026-01-25T23:59:59Z",
      "midPeak": {"cost": 157.4, "consumption": 425.05},
      "offPeak": {"cost": 41.8, "consumption": 214.817},
      "onPeak": {"cost": 14.19, "consumption": 35.915},
      "flatRate": null,
      "categories": [
        {"name": "spaceHeating", "usage": 433, "cost": 137},
        {"name": "waterHeating", "usage": 73, "cost": 23},
        {"name": "alwaysOn", "usage": 59, "cost": 19},
        {"name": "refrigeration", "usage": 33, "cost": 10},
        {"name": "lighting", "usage": 16, "cost": 5},
        {"name": "entertainment", "usage": 15, "cost": 5},
        {"name": "cooking", "usage": 14, "cost": 4},
        {"name": "laundry", "usage": 12, "cost": 4},
        {"name": "other", "usage": 19, "cost": 6}
      ]
    }
  ],
  "isSuccess": true
}
```

### GET .../MeterInsight/{partner}/{contract}/{premise}/appliance-usage?start=YYYY-MM-DD&end=YYYY-MM-DD (auth required)

```json
{
  "subStatusCode": "SUCCESS",
  "message": "Successfully executed query for query Appliance Uasge",
  "data": [
    {
      "billStartDate": "2026-02-26T00:00:00Z",
      "billEndDate": "2026-03-25T23:59:59Z",
      "appliances": [
        {"category": "spaceHeating", "consumption": 226, "cost": 72},
        {"category": "alwaysOn", "consumption": 46, "cost": 14},
        {"category": "waterHeating", "consumption": 45, "cost": 14},
        {"category": "refrigeration", "consumption": 30, "cost": 10},
        {"category": "cooking", "consumption": 9, "cost": 3},
        {"category": "entertainment", "consumption": 8, "cost": 3},
        {"category": "lighting", "consumption": 7, "cost": 2},
        {"category": "laundry", "consumption": 7, "cost": 2},
        {"category": "other", "consumption": 28, "cost": 9},
        {"category": "total", "consumption": 406, "cost": 129.04}
      ]
    }
  ],
  "isSuccess": true
}
```

### GET .../MeterInsight/{partner}/{contract}/{premise}/bill-period (auth required)

Response shape matches existing integration's bill-period endpoint (same JSON structure as current web portal).

---

## Feature Flags (Azure App Configuration)

```
GET https://eiresportalroi-prd-mobile-config-01.azconfig.io/kv?api-version=1.0
Authorization: HMAC-SHA256 (credential-based)
```

Key flags:
- `insightsEnabled: true` — Insights tab
- `smartInsights: true` — Smart insights
- `netZeroHub: true` — Net Zero Hub
- Seasonal: christmas, easter, halloween, stPaddys, loveMonth, earthDay

---

## App Metadata

- **Package**: `ie.electricireland.resmobile` (Android) / App ID `6444361812` (iOS)
- **Framework**: React Native 0.77.1
- **Firebase project**: `electric-ireland---roi-res` (project number 340720950351)
- **User-Agent (native)**: `ElectricIreland/150550 CFNetwork/3860.500.112 Darwin/25.4.0`
- **User-Agent (webview)**: `Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15`
