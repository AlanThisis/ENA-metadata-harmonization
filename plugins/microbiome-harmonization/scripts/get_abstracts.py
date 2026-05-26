#!/usr/bin/env python3
"""Fetch PubMed/PMC abstracts for PMID or PMCID inputs.

Examples
--------
Single ID, print abstract text:
    python scripts/get_abstracts.py PMC3531190

Multiple IDs, print CSV to stdout:
    python scripts/get_abstracts.py PMC3531190 27102758

Multiple IDs, write CSV to a file:
    python scripts/get_abstracts.py PMC3531190 27102758 -o abstracts.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
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
EFETCH_BATCH_SIZE = 200

PMCID_RE = re.compile(r"^PMC\d+(?:\.\d+)?$", re.IGNORECASE)
PMID_RE = re.compile(r"^\d+$")


@dataclass
class Result:
    requested_id: str
    input_type: str
    pmid: str = ""
    pmcid: str = ""
    abstract: str = ""
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
            data = json.loads(text)
            for record in data.get("records", []):
                requested = str(record.get("requested-id", "")).upper()
                records[requested] = {
                    "pmid": str(record.get("pmid", "") or ""),
                    "pmcid": str(record.get("pmcid", "") or ""),
                    "error": str(record.get("errmsg", "") or record.get("error", "") or ""),
                }
        return records

    def fetch_pubmed_abstracts(self, pmids: list[str]) -> dict[str, str]:
        abstracts: dict[str, str] = {}
        for batch in chunked(pmids, EFETCH_BATCH_SIZE):
            text = self._get_text(
                EUTILS_BASE,
                {
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "retmode": "xml",
                },
            )
            root = ET.fromstring(text)
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find("./MedlineCitation/PMID")
                if pmid_el is None or not (pmid_el.text or "").strip():
                    continue
                pmid = (pmid_el.text or "").strip()
                abstract_parts = []
                for abstract_el in article.findall(".//Abstract/AbstractText"):
                    label = (abstract_el.attrib.get("Label") or "").strip()
                    text_part = normalize_xml_text(abstract_el)
                    if not text_part:
                        continue
                    abstract_parts.append(f"{label}: {text_part}" if label else text_part)
                abstracts[pmid] = "\n".join(abstract_parts).strip()
        return abstracts

    def fetch_pmc_abstracts(self, pmcids: list[str]) -> dict[str, str]:
        abstracts: dict[str, str] = {}
        for batch in chunked(pmcids, EFETCH_BATCH_SIZE):
            text = self._get_text(
                EUTILS_BASE,
                {
                    "db": "pmc",
                    "id": ",".join(batch),
                    "retmode": "xml",
                },
            )
            root = ET.fromstring(text)
            for article in root.findall(".//article"):
                pmcid = extract_pmcid_from_article(article)
                if not pmcid:
                    continue
                abstract_nodes = article.findall("./front/article-meta/abstract")
                parts = [normalize_xml_text(node) for node in abstract_nodes]
                abstracts[pmcid.upper()] = "\n\n".join(part for part in parts if part).strip()
        return abstracts


def normalize_xml_text(node: ET.Element) -> str:
    text = "".join(node.itertext())
    return " ".join(text.split())


def extract_pmcid_from_article(article: ET.Element) -> str:
    for article_id in article.findall(".//article-id"):
        pub_id_type = (article_id.attrib.get("pub-id-type") or "").lower()
        value = (article_id.text or "").strip()
        if not value:
            continue
        if pub_id_type in {"pmc", "pmcid", "pmcid-ver", "pmcaid"} and value.upper().startswith("PMC"):
            return value.upper()
        if PMCID_RE.fullmatch(value):
            return value.upper()
    return ""


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


def fetch_results(ids: list[str]) -> list[Result]:
    client = NCBIClient()
    results = [Result(requested_id=value, input_type=classify_id(value)) for value in ids]

    pmid_values = [result.requested_id for result in results if result.input_type == "pmid"]
    pmcid_values = [result.requested_id.upper() for result in results if result.input_type == "pmcid"]

    pmcid_lookup: dict[str, dict[str, str]] = {}
    if pmcid_values:
        pmcid_lookup = client.convert_pmcids(pmcid_values)

    pubmed_ids: list[str] = []
    for result in results:
        if result.input_type == "pmid":
            result.pmid = result.requested_id
            pubmed_ids.append(result.pmid)
            continue

        key = result.requested_id.upper()
        converted = pmcid_lookup.get(key, {})
        result.pmcid = converted.get("pmcid", key)
        result.pmid = converted.get("pmid", "")
        if converted.get("error"):
            result.error = converted["error"]
        if result.pmid:
            pubmed_ids.append(result.pmid)

    pubmed_abstracts = client.fetch_pubmed_abstracts(unique_preserving_order(pubmed_ids)) if pubmed_ids else {}

    pmc_fallback_ids = []
    for result in results:
        if result.pmid and pubmed_abstracts.get(result.pmid):
            result.abstract = pubmed_abstracts[result.pmid]
        elif result.input_type == "pmcid":
            pmc_fallback_ids.append(result.pmcid or result.requested_id.upper())

    pmc_abstracts = client.fetch_pmc_abstracts(unique_preserving_order(pmc_fallback_ids)) if pmc_fallback_ids else {}

    for result in results:
        if result.abstract:
            continue
        if result.input_type == "pmcid":
            lookup_key = (result.pmcid or result.requested_id).upper()
            if pmc_abstracts.get(lookup_key):
                result.abstract = pmc_abstracts[lookup_key]
        if not result.abstract and not result.error:
            result.error = "Abstract not found"

    return results


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch abstract text for PMID/PMCID input(s).",
        epilog=(
            "Single ID prints the abstract text directly. Multiple IDs produce CSV with "
            "requested_id,input_type,pmid,pmcid,abstract,error."
        ),
    )
    parser.add_argument(
        "ids",
        nargs="+",
        help="One or more PMIDs or PMCIDs (for example: 27102758 or PMC3531190).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write CSV output to this path. If omitted, CSV is printed to stdout for multi-ID input.",
    )
    return parser


def write_csv(results: list[Result], output_path: str | None) -> None:
    fieldnames = ["requested_id", "input_type", "pmid", "pmcid", "abstract", "error"]
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
        if result.abstract:
            print(result.abstract)
            return 0
        print(result.error or "Abstract not found", file=sys.stderr)
        return 1

    write_csv(results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
