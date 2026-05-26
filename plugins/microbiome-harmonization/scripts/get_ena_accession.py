#!/usr/bin/env python3
"""Extract ENA/SRA project accessions from PMC full-text using regex.

Examples
--------
Single PMID/PMCID, print accessions:
    python scripts/get_ena_accession.py PMC4681099

Multiple IDs, print CSV to stdout:
    python scripts/get_ena_accession.py PMC4681099 38243197

Multiple IDs, write CSV to a file:
    python scripts/get_ena_accession.py PMC4681099 38243197 -o accessions.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import socket
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

import requests


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
IDCONV_BASE = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
TOOL_NAME = "ena_metadata_harmonization"
MAX_REQUESTS_PER_SECOND = 3.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0 / MAX_REQUESTS_PER_SECOND
IDCONV_BATCH_SIZE = 200

PMCID_RE = re.compile(r"^PMC\d+(?:\.\d+)?$", re.IGNORECASE)
PMID_RE = re.compile(r"^\d+$")

# ENA/SRA project accession patterns
ACCESSION_PATTERNS = (
    re.compile(r"PRJ(?:E|D|N)[A-Z][0-9]+", re.IGNORECASE),
    re.compile(r"(?:E|D|S)RP[0-9]{6,}", re.IGNORECASE),
)


@dataclass
class Result:
    requested_id: str
    input_type: str
    pmid: str = ""
    pmcid: str = ""
    accessions: str = ""
    error: str = ""


class NCBIClient:
    def __init__(self, tool: str = TOOL_NAME) -> None:
        self.tool = tool
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def _get_text(self, base_url: str, params: dict[str, str]) -> str:
        query = dict(params)
        query["tool"] = self.tool
        self._throttle()
        try:
            response = requests.get(
                base_url,
                params=query,
                headers={"User-Agent": self.tool},
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = exc.response.text if exc.response is not None else ""
            raise RuntimeError(f"HTTP error for {response.url}: {detail}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Request failed for {base_url}: {exc}") from exc

        self._last_request_time = time.monotonic()
        return response.text

    def convert_pmcids(self, pmcids: list[str]) -> dict[str, dict[str, str]]:
        records: dict[str, dict[str, str]] = {}
        for batch in chunked(pmcids, IDCONV_BATCH_SIZE):
            text = self._get_text(
                IDCONV_BASE,
                {
                    "ids": ",".join(batch),
                    "format": "json",
                },
            )
            import json
            data = json.loads(text)
            for record in data.get("records", []):
                requested = str(record.get("requested-id", "")).upper()
                records[requested] = {
                    "pmid": str(record.get("pmid", "") or ""),
                    "pmcid": str(record.get("pmcid", "") or ""),
                    "error": str(record.get("errmsg", "") or record.get("error", "") or ""),
                }
        return records

    def fetch_pmc_fulltext_xml(self, pmcid: str) -> str:
        uid = pmcid.replace("PMC", "", 1)
        text = self._get_text(
            EUTILS_BASE,
            {
                "db": "pmc",
                "id": uid,
                "retmode": "xml",
            },
        )
        if re.search(r"<\s*error\b", text, re.IGNORECASE):
            raise RuntimeError(f"NCBI returned error for {pmcid}")
        return text


def chunked(values: Iterable[str], size: int) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def classify_id(value: str) -> str:
    normalized = value.strip()
    if PMCID_RE.fullmatch(normalized):
        return "pmcid"
    if PMID_RE.fullmatch(normalized):
        return "pmid"
    raise ValueError(f"Unrecognized ID format: {value!r}. Expected PMID digits or PMCID like PMC12345.")


def extract_accessions(text: str) -> list[str]:
    """Extract unique ENA/SRA accessions from text via regex."""
    found: set[str] = set()
    for pattern in ACCESSION_PATTERNS:
        for match in pattern.findall(text):
            found.add(match.upper())
    return sorted(found)


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def fetch_results(ids: list[str]) -> list[Result]:
    client = NCBIClient()
    results = [Result(requested_id=value, input_type=classify_id(value)) for value in ids]

    pmcid_values = [result.requested_id.upper() for result in results if result.input_type == "pmcid"]
    pmcid_lookup: dict[str, dict[str, str]] = {}
    if pmcid_values:
        pmcid_lookup = client.convert_pmcids(pmcid_values)

    for result in results:
        if result.input_type == "pmid":
            result.pmid = result.requested_id
            continue

        key = result.requested_id.upper()
        converted = pmcid_lookup.get(key, {})
        result.pmcid = converted.get("pmcid", key)
        result.pmid = converted.get("pmid", "")
        if converted.get("error"):
            result.error = converted["error"]

    pmcids_to_fetch = unique_preserving_order(
        [result.pmcid or result.requested_id.upper() for result in results if result.input_type == "pmcid"]
    )

    for pmcid in pmcids_to_fetch:
        try:
            xml_text = client.fetch_pmc_fulltext_xml(pmcid)
            accessions = extract_accessions(xml_text)
        except Exception as exc:
            accessions = []
            error_msg = str(exc)
        else:
            error_msg = ""

        for result in results:
            if result.input_type == "pmcid" and (result.pmcid or result.requested_id).upper() == pmcid:
                if accessions:
                    result.accessions = "; ".join(accessions)
                elif not error_msg:
                    result.accessions = "ENA_NOT_FOUND"
                else:
                    result.error = error_msg

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract ENA/SRA project accessions from PMC full-text using regex.",
        epilog=(
            "Single ID prints accessions one per line. Multiple IDs produce CSV with "
            "requested_id,input_type,pmid,pmcid,accessions,error."
        ),
    )
    parser.add_argument(
        "ids",
        nargs="+",
        help="One or more PMIDs or PMCIDs (for example: 38243197 or PMC4681099).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write CSV output to this path. If omitted, CSV is printed to stdout for multi-ID input.",
    )
    return parser


def write_csv(results: list[Result], output_path: str | None) -> None:
    fieldnames = ["requested_id", "input_type", "pmid", "pmcid", "accessions", "error"]
    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(result.__dict__)
        return

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for result in results:
        writer.writerow(result.__dict__)
    sys.stdout.write(buffer.getvalue())


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        results = fetch_results(args.ids)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if len(results) == 1 and not args.output:
        result = results[0]
        if result.accessions:
            for acc in result.accessions.split("; "):
                print(acc)
            return 0
        print(result.error or "ENA_NOT_FOUND", file=sys.stderr)
        return 1

    write_csv(results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
