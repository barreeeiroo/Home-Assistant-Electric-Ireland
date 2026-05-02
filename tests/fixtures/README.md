# Fixture strategy

These fixtures capture realistic Electric Ireland API edge cases while staying compatible with the current parsing logic. They are used to validate schema handling and to document expected response shapes.

Capture policy: add only minimal, representative payloads for new edge cases so tests stay small and stable. Refresh fixtures whenever the live response shape changes in a way that affects parsing.

Anonymization policy: fixtures must contain no real customer data, emails, or account numbers; only documented placeholders such as `test@example.com` and `100000001` are allowed. Any new fixture should be checked with the schema helpers before being committed.

Refresh policy: update fixtures when the integration adds or removes required fields, or when Electric Ireland changes the API response format. Keep historical examples unless they become invalid or misleading.
