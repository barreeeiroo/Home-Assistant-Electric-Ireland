#!/usr/bin/env python3
"""Standalone capture/anonymize utility for Electric Ireland fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import aiohttp

BASE_URL = "https://youraccountonline.electricireland.ie"

ANON_ACCOUNT = "100000001"
ANON_EMAIL = "test@example.com"
ANON_PARTNER = "PARTNER_001"
ANON_CONTRACT = "CONTRACT_001"
ANON_PREMISE = "PREMISE_001"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
NINE_DIGIT_RE = re.compile(r"\b\d{9}\b")
PII_KEYS = {"account", "accountNumber", "email", "partner", "contract", "premise"}
DATE_KEYS = {"date", "endDate", "startDate", "timestamp", "intervalEnd"}

LOGGER = logging.getLogger("capture_fixtures")


def _shift_hour(hour: int, offset: int) -> int:
    return (hour + offset) % 24


def _perturb_number(value: float, rng: random.Random) -> float:
    return round(value * rng.uniform(0.7, 1.3), 6)


def _seeded_rng() -> random.Random:
    return random.Random(42)  # noqa: S311


def _shift_datetime_text(value: str, rng: random.Random) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    shifted = dt + timedelta(hours=rng.choice((-2, -1, 0, 1, 2)))
    return shifted.isoformat().replace("+00:00", "Z")


class _LoginTokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.source: str | None = None
        self.rvt: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attr_map = dict(attrs)
        name = attr_map.get("name")
        value = attr_map.get("value")
        if name == "Source" and isinstance(value, str):
            self.source = value
        if name == "rvt" and isinstance(value, str):
            self.rvt = value


class _ModelDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partner: str | None = None
        self.contract: str | None = None
        self.premise: str | None = None
        self._in_model_data = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        attr_map = dict(attrs)
        if attr_map.get("id") == "modelData":
            self._in_model_data = True
            self.partner = attr_map.get("data-partner")
            self.contract = attr_map.get("data-contract")
            self.premise = attr_map.get("data-premise")


class _AccountParser(HTMLParser):
    def __init__(self, account_number: str) -> None:
        super().__init__()
        self.account_number = account_number
        self.capture_form = False
        self.found = False
        self.payload: dict[str, str] = {"triggers_event": "AccountSelection.ToInsights"}
        self._in_account_div = False
        self._is_electricity = False
        self._current_tag: str | None = None
        self._current_attrs: dict[str, str | None] = {}
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        self._current_tag = tag
        self._current_attrs = attr_map
        if tag == "div" and attr_map.get("class") == "my-accounts__item":
            self._in_account_div = True
            self._is_electricity = False
            self.payload = {"triggers_event": "AccountSelection.ToInsights"}
        if self._in_account_div and tag == "h2" and attr_map.get("class") == "account-electricity-icon":
            self._is_electricity = True
        if self.capture_form and tag == "input":
            name = attr_map.get("name")
            value = attr_map.get("value")
            if isinstance(name, str) and isinstance(value, str):
                self.payload[name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_account_div:
            self._in_account_div = False
            self.capture_form = False
            self._text.clear()
        if tag == "form" and self.capture_form:
            self.capture_form = False

    def handle_data(self, data: str) -> None:
        if not self._in_account_div:
            return
        self._text.append(data)
        if self.account_number in "".join(self._text) and self._is_electricity:
            self.found = True
        if self.found and self._current_tag == "form" and self._current_attrs.get("action") == "/Accounts/OnEvent":
            self.capture_form = True


def _anonymize_value(key: str | None, value: Any, rng: random.Random) -> Any:
    if key in PII_KEYS:
        if key == "account" or key == "accountNumber":
            return ANON_ACCOUNT
        if key == "email":
            return ANON_EMAIL
        if key == "partner":
            return ANON_PARTNER
        if key == "contract":
            return ANON_CONTRACT
        if key == "premise":
            return ANON_PREMISE

    if isinstance(value, dict):
        return {k: _anonymize_value(k, v, rng) for k, v in value.items()}

    if isinstance(value, list):
        return [_anonymize_value(key, item, rng) for item in value]

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, int):
        if key == "intervalEnd":
            return value + (rng.choice((-2, -1, 0, 1, 2)) * 3600)
        if key and key.lower() == "hour":
            return _shift_hour(value, rng.choice((-2, -1, 0, 1, 2)))
        return value

    if isinstance(value, float):
        if key in {"consumption", "cost"}:
            return _perturb_number(value, rng)
        return value

    if isinstance(value, str):
        anonymized = EMAIL_RE.sub(ANON_EMAIL, value)
        anonymized = NINE_DIGIT_RE.sub(ANON_ACCOUNT, anonymized)
        anonymized = anonymized.replace(ANON_PARTNER, ANON_PARTNER)
        anonymized = anonymized.replace(ANON_CONTRACT, ANON_CONTRACT)
        anonymized = anonymized.replace(ANON_PREMISE, ANON_PREMISE)
        if key in DATE_KEYS or re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", anonymized):
            anonymized = _shift_datetime_text(anonymized, rng)
        return anonymized

    return value


def anonymize_text(text: str, rng: random.Random) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if payload is not None:
        anonymized = _anonymize_value(None, payload, rng)
        return json.dumps(anonymized, indent=2, ensure_ascii=False, sort_keys=True)

    anonymized = EMAIL_RE.sub(ANON_EMAIL, text)
    anonymized = NINE_DIGIT_RE.sub(ANON_ACCOUNT, anonymized)
    anonymized = re.sub(r'data-partner="[^"]+"', f'data-partner="{ANON_PARTNER}"', anonymized)
    anonymized = re.sub(r'data-contract="[^"]+"', f'data-contract="{ANON_CONTRACT}"', anonymized)
    anonymized = re.sub(r'data-premise="[^"]+"', f'data-premise="{ANON_PREMISE}"', anonymized)
    return anonymized


def verify_no_pii(fixtures_dir: Path) -> list[Path]:
    leaked: list[Path] = []
    for path in fixtures_dir.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in EMAIL_RE.findall(content):
            if match.lower() != ANON_EMAIL:
                leaked.append(path)
                break
        else:
            for match in NINE_DIGIT_RE.findall(content):
                if match != ANON_ACCOUNT:
                    leaked.append(path)
                    break
    return leaked


def _extract_login_tokens(html: str, cookies: Mapping[str, Any]) -> tuple[str | None, str | None]:
    parser = _LoginTokenParser()
    parser.feed(html)
    source = parser.source
    rvt = cookies.get("rvt")
    rvt_value = rvt.value if rvt else None
    if not rvt_value:
        rvt_value = parser.rvt
    return (source if isinstance(source, str) else None, rvt_value if isinstance(rvt_value, str) else None)


async def _perform_login(session: aiohttp.ClientSession, username: str, password: str) -> str:
    timeout = aiohttp.ClientTimeout(total=30)
    async with session.get(f"{BASE_URL}/", timeout=timeout) as response:
        response.raise_for_status()
        html = await response.text()
        source, rvt = _extract_login_tokens(html, response.cookies)
    if not source or not rvt:
        raise RuntimeError("Could not extract login tokens from the login page")

    async with session.post(
        f"{BASE_URL}/",
        data={
            "LoginFormData.UserName": username,
            "LoginFormData.Password": password,
            "rvt": rvt,
            "Source": source,
            "PotText": "",
            "__EiTokPotText": "",
            "ReturnUrl": "",
            "AccountNumber": "",
        },
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        return await response.text()


async def _discover_account_html(
    session: aiohttp.ClientSession,
    dashboard_html: str,
    account_number: str,
) -> tuple[str, str, str, str, str]:
    from bs4 import BeautifulSoup, Tag

    soup = BeautifulSoup(dashboard_html, "html.parser")
    account_divs = soup.find_all("div", {"class": "my-accounts__item"})
    payload: dict[str, str] = {}
    found = False

    for div in account_divs:
        acct_el = div.find("p", {"class": "account-number"})
        if not acct_el:
            continue
        if account_number not in acct_el.text.strip():
            continue
        is_elec = div.find_all("h2", {"class": "account-electricity-icon"})
        if len(is_elec) != 1:
            continue
        form = div.find("form", {"action": "/Accounts/OnEvent"})
        if not isinstance(form, Tag):
            continue
        for inp in form.find_all("input"):
            name = inp.get("name")
            value = inp.get("value")
            if isinstance(name, str) and isinstance(value, str):
                payload[name] = value
        payload["triggers_event"] = "AccountSelection.ToInsights"
        found = True
        break

    if not found:
        raise RuntimeError(f"Account {account_number} was not found after login")

    timeout = aiohttp.ClientTimeout(total=30)
    async with session.post(
        f"{BASE_URL}/Accounts/OnEvent",
        data=payload,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        insights_html = await response.text()

    insights_soup = BeautifulSoup(insights_html, "html.parser")
    model_div = insights_soup.find("div", {"id": "modelData"})
    if not isinstance(model_div, Tag):
        raise RuntimeError("Could not find model data on the insights page")

    partner = model_div.get("data-partner")
    contract = model_div.get("data-contract")
    premise = model_div.get("data-premise")
    if not all(isinstance(v, str) for v in (partner, contract, premise)):
        raise RuntimeError("Could not extract meter IDs from insights page")

    assert isinstance(partner, str)
    assert isinstance(contract, str)
    assert isinstance(premise, str)
    return dashboard_html, insights_html, partner, contract, premise


async def _fetch_json(session: aiohttp.ClientSession, url: str, params: dict[str, str] | None = None) -> str:
    timeout = aiohttp.ClientTimeout(total=30)
    async with session.get(url, params=params, timeout=timeout) as response:
        response.raise_for_status()
        return await response.text()


async def capture(username: str, password: str, account_number: str, output_dir: Path, fixture_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    fixture_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    resolver = aiohttp.resolver.ThreadedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver)
    async with aiohttp.ClientSession(connector=connector) as session:
        login_html = await _perform_login(session, username, password)
        login_path = output_dir / "login-dashboard.raw.html"
        login_path.write_text(login_html, encoding="utf-8")
        (fixture_dir / "login-dashboard.html").write_text(
            anonymize_text(login_html, _seeded_rng()),
            encoding="utf-8",
        )

        dashboard_html, insights_html, partner, contract, premise = await _discover_account_html(
            session, login_html, account_number
        )
        (output_dir / "dashboard.raw.html").write_text(dashboard_html, encoding="utf-8")
        (output_dir / "insights.raw.html").write_text(insights_html, encoding="utf-8")
        (fixture_dir / "dashboard.html").write_text(
            anonymize_text(dashboard_html, _seeded_rng()),
            encoding="utf-8",
        )
        (fixture_dir / "insights.html").write_text(
            anonymize_text(insights_html, _seeded_rng()),
            encoding="utf-8",
        )

        bill_url = f"{BASE_URL}/MeterInsight/{partner}/{contract}/{premise}/bill-period"
        bill_periods = await _fetch_json(session, bill_url)
        (output_dir / "bill-period.raw.json").write_text(bill_periods, encoding="utf-8")
        (fixture_dir / "bill-period.json").write_text(
            anonymize_text(bill_periods, _seeded_rng()),
            encoding="utf-8",
        )

        hourly_url = f"{BASE_URL}/MeterInsight/{partner}/{contract}/{premise}/hourly-usage"
        today = datetime.now(tz=UTC).date()
        for day_offset in range(2):
            target_date = today - timedelta(days=day_offset)
            hourly = await _fetch_json(session, hourly_url, params={"date": target_date.isoformat()})
            raw_name = f"hourly-usage.{target_date.isoformat()}.raw.json"
            anon_name = f"hourly-usage.{target_date.isoformat()}.json"
            (output_dir / raw_name).write_text(hourly, encoding="utf-8")
            (fixture_dir / anon_name).write_text(
                anonymize_text(hourly, _seeded_rng()),
                encoding="utf-8",
            )


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _anonymize_file(input_path: Path, output_path: Path | None) -> None:
    rng = _seeded_rng()
    anonymized = anonymize_text(_load_text(input_path), rng)
    if output_path is None:
        sys.stdout.write(anonymized)
    else:
        _write_text(output_path, anonymized)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and anonymize Electric Ireland fixtures.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify fixtures under tests/fixtures/real/ for PII leakage.",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("EI_USERNAME"),
        help="Electric Ireland username (or EI_USERNAME).",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("EI_PASSWORD"),
        help="Electric Ireland password (or EI_PASSWORD).",
    )
    parser.add_argument("--account-number", help="Target 9-digit account number for capture.")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=Path("tests/fixtures/real"),
        help="Destination for anonymized fixtures.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "ei-fixtures",
        help="Directory for raw responses.",
    )
    parser.add_argument(
        "--anonymize-file",
        type=Path,
        help="Anonymize a single JSON/text file and write to --output-file or stdout.",
    )
    parser.add_argument("--output-file", type=Path, help="Output path for --anonymize-file.")
    return parser


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.verify:
        leaked = verify_no_pii(args.fixtures_dir)
        if leaked:
            for path in leaked:
                LOGGER.error("PII detected in %s", path)
            return 1
        LOGGER.info("No PII detected in %s", args.fixtures_dir)
        return 0

    if args.anonymize_file is not None:
        await _anonymize_file(args.anonymize_file, args.output_file)
        return 0

    if not args.username or not args.password:
        parser.error(
            "--username/--password or EI_USERNAME/EI_PASSWORD are required unless --verify or --anonymize-file is used"
        )
    if not args.account_number:
        parser.error("--account-number is required for capture mode")

    try:
        await capture(
            args.username,
            args.password,
            args.account_number,
            args.output_dir,
            args.fixtures_dir,
        )
    except aiohttp.ClientError as err:
        LOGGER.error("Network error during capture: %s", err)
        return 1
    except RuntimeError as err:
        LOGGER.error("Capture failed: %s", err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
