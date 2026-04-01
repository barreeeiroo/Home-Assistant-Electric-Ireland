# Security Policy

## Credential handling

This integration stores your Electric Ireland username and password in Home Assistant's configuration entry storage. Credentials are:

- Stored **locally** on your Home Assistant instance only
- **Never** transmitted to any server other than Electric Ireland's own portal (`youraccountonline.electricireland.ie`)
- **Automatically redacted** from diagnostics output

This integration does **not** operate any external server, cloud service, or data collection infrastructure.

## Reporting a vulnerability

If you discover a security vulnerability in this integration, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email the maintainers or use [GitHub's private vulnerability reporting](https://github.com/barreeeiroo/Home-Assistant-Electric-Ireland/security/advisories/new)

## Best practices for users

- **Never** share debug logs without redacting sensitive information (credentials, session tokens, account numbers)
- **Never** post Electric Ireland cookies, session data, or raw portal HTML in GitHub issues
- Keep your Home Assistant instance secured — credentials are only as safe as your HA installation
