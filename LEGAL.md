# Legal Notice

## Disclaimer

Electric Ireland Insights is an independent, community-built, open-source integration for Home Assistant. It is **not affiliated with, authorized by, maintained by, or endorsed by** Electric Ireland, ESB Group, or any of their subsidiaries, partners, or affiliates.

"Electric Ireland" is a registered trademark of Electric Ireland Ltd. All product names, trademarks, and registered trademarks mentioned in this project are the property of their respective owners. The use of these names is solely to describe the integration's functionality and does not imply endorsement, affiliation, or sponsorship.

## How this integration works

This integration authenticates with the Electric Ireland customer portal using credentials provided by the user and retrieves energy consumption data via web scraping. **There is no official API provided by Electric Ireland for this purpose.** The integration mimics standard browser interactions to access data that the user is already entitled to view through their account.

Changes to the Electric Ireland website, its underlying services, or its terms of use may break this integration at any time without notice. As the authors are not affiliated with nor in contact with Electric Ireland, there is no advance knowledge of such changes and no guarantee of continued functionality.

## Terms of service

Users are solely responsible for determining whether their use of this integration complies with Electric Ireland's terms of service and all applicable laws.

As of April 2026, Electric Ireland's [Terms and Conditions](https://youraccountonline.electricireland.ie/TermsAndConditions) for their online portal require users to "use the Site and the facilities made available on it only for their intended purposes, and must at all times act in good faith when doing so." The terms do not contain any explicit prohibition of automated access, scraping, bots, or third-party tools. However, terms may be updated at any time — users should review the current terms before use.

The authors make no representation that use of this integration is or will remain permitted under Electric Ireland's terms.

## Data portability context

Under the EU General Data Protection Regulation (GDPR), Article 20 grants individuals the right to receive their personal data — including energy consumption records — in a structured, commonly used, and machine-readable format. While this right creates an obligation on data controllers (such as Electric Ireland) to provide portable data, it does not by itself authorize automated access methods such as web scraping. Users should be aware of this distinction.

This integration is designed to help users import their own energy data into Home Assistant for personal use. It does not collect, store, transmit, or share user data with any third party. All data remains on the user's local Home Assistant instance.

## Privacy and security

- **Credentials**: Your Electric Ireland username and password are stored locally in Home Assistant's configuration storage. They are never transmitted to any server other than Electric Ireland's own portal.
- **No backend**: This integration does not operate any external server, cloud service, or data collection infrastructure. All processing happens locally on your Home Assistant instance.
- **Diagnostics**: The integration's diagnostics feature automatically redacts sensitive information (username, password, account number, meter identifiers) before exposing any data.
- **Logs**: Debug logs may contain session tokens or request details. Users should redact sensitive information before sharing logs in bug reports or public forums.

## Limitation of liability

This software is provided under the terms of the [GNU General Public License v3.0](LICENSE), which includes the following warranty disclaimer (sections 15–16):

> THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW. THE PROGRAM IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

The authors and contributors of this project accept no responsibility or liability for any consequences arising from the use of this integration. This includes, but is not limited to:

- Account suspension, restriction, or termination by Electric Ireland
- Service interruptions caused by changes to the Electric Ireland portal
- Inaccurate, incomplete, or missing energy data
- Any legal action taken by Electric Ireland, ESB Group, or any of their partners or affiliates against users of this software

Users should carefully consider these risks before installing or using this integration.

## Trademarks

All product names, logos, and brands used in this project are the property of their respective owners. They are used only as reasonably necessary to identify the service that the integration is compatible with. Such use does not imply any affiliation with or endorsement by the trademark holders.

The integration's icon is used for identification purposes within the Home Assistant user interface only.

## Origin

This project is a fork of [barreeeiroo/Home-Assistant-Electric-Ireland](https://github.com/barreeeiroo/Home-Assistant-Electric-Ireland), originally created by [@barreeeiroo](https://github.com/barreeeiroo) and licensed under the GNU General Public License v3.0. This fork continues and extends the original work under the same license.

## Contact

If you are a representative of Electric Ireland and have concerns about this project, please open a GitHub issue or contact the maintainers directly. We are committed to acting in good faith and will respond promptly to any legitimate concerns.
