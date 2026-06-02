#!/usr/bin/env python3
"""Fetch PubTator3 disease entities for PMID or PMCID inputs.

Examples
--------
Single ID, print one disease entity per line:
    python scripts/get_disease_entities.py PMC10797958

Multiple IDs, print CSV to stdout:
    python scripts/get_disease_entities.py PMC10797958 38243197

Multiple IDs from a CSV column, write output CSV:
    python scripts/get_disease_entities.py --input-csv papers.csv --id-column pmid -o diseases.csv

Multiple IDs, write CSV to a file:
    python scripts/get_disease_entities.py PMC10797958 38243197 -o diseases.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Iterable

import requests


IDCONV_BASE = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
PUBTATOR3_EXPORT_BASE = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
TOOL_NAME = "ena_metadata_harmonization"
MAX_REQUESTS_PER_SECOND = 3.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0 / MAX_REQUESTS_PER_SECOND
IDCONV_BATCH_SIZE = 200
PUBTATOR_BATCH_SIZE = 100

PMCID_RE = re.compile(r"^PMC\d+(?:\.\d+)?$", re.IGNORECASE)
PMID_RE = re.compile(r"^\d+$")


@dataclass
class DiseaseEntity:
    name: str
    mesh_id: str
    accession: str = ""


@dataclass
class Result:
    requested_id: str
    input_type: str
    pmid: str = ""
    pmcid: str = ""
    disease_names: list[str] = field(default_factory=list)
    disease_ids: list[str] = field(default_factory=list)
    error: str = ""


class RateLimitedClient:
    def __init__(self, tool: str = TOOL_NAME) -> None:
        self.tool = tool
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def get_json(self, base_url: str, params: dict[str, str]) -> dict:
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
        return response.json()


def chunked(values: Iterable[str], size: int) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def classify_id(value: str) -> str:
    normalized = value.strip()
    if PMCID_RE.fullmatch(normalized):
        return "pmcid"
    if PMID_RE.fullmatch(normalized):
        return "pmid"
    raise ValueError(f"Unrecognized ID format: {value!r}. Expected PMID digits or PMCID like PMC12345.")


def load_ids_from_csv(csv_path: str, column: str | None) -> list[str]:
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        if not headers:
            raise ValueError(f"CSV file {csv_path!r} appears to be empty.")
        if column is None:
            col = headers[0]
            print(f"  No --id-column specified; using first column: {col!r}", file=sys.stderr)
        else:
            col = column
            if col not in headers:
                lower_map = {h.lower(): h for h in headers}
                if col.lower() in lower_map:
                    col = lower_map[col.lower()]
                else:
                    raise ValueError(
                        f"Column {column!r} not found in {csv_path!r}. "
                        f"Available columns: {', '.join(headers)}"
                    )
        ids = [row[col].strip() for row in reader if (row.get(col) or "").strip()]
    return ids


def convert_pmcids(client: RateLimitedClient, pmcids: list[str]) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for batch in chunked(pmcids, IDCONV_BATCH_SIZE):
        data = client.get_json(
            IDCONV_BASE,
            {
                "ids": ",".join(batch),
                "format": "json",
            },
        )
        for record in data.get("records", []):
            requested = str(record.get("requested-id", "")).upper()
            records[requested] = {
                "pmid": str(record.get("pmid", "") or ""),
                "pmcid": str(record.get("pmcid", "") or ""),
                "error": str(record.get("errmsg", "") or record.get("error", "") or ""),
            }
    return records


def fetch_disease_entities(client: RateLimitedClient, pmids: list[str]) -> dict[str, list[DiseaseEntity]]:
    disease_map: dict[str, list[DiseaseEntity]] = {}
    for batch in chunked(pmids, PUBTATOR_BATCH_SIZE):
        data = client.get_json(
            PUBTATOR3_EXPORT_BASE,
            {
                "pmids": ",".join(batch),
            },
        )
        for article in data.get("PubTator3", []):
            pmid = str(article.get("id") or article.get("pmid") or "").strip()
            if not pmid:
                continue

            by_mesh_id: dict[str, DiseaseEntity] = {}
            ordered_fallback: dict[str, DiseaseEntity] = {}

            for passage in article.get("passages", []):
                for annotation in passage.get("annotations", []):
                    infons = annotation.get("infons", {})
                    if infons.get("type") != "Disease":
                        continue

                    name = str(infons.get("name") or annotation.get("text") or "").strip()
                    mesh_id = str(infons.get("normalized_id") or infons.get("identifier") or "").strip()
                    accession = str(infons.get("accession") or "").strip()
                    if not name:
                        continue

                    entity = DiseaseEntity(name=name, mesh_id=mesh_id, accession=accession)
                    if mesh_id:
                        by_mesh_id.setdefault(mesh_id, entity)
                    else:
                        ordered_fallback.setdefault(name.lower(), entity)

            combined = list(by_mesh_id.values()) + list(ordered_fallback.values())
            disease_map[pmid] = combined
    return disease_map


def fetch_results(ids: list[str]) -> list[Result]:
    client = RateLimitedClient()
    total = len(ids)
    print(f"Fetching disease entities for {total} ID(s)...", file=sys.stderr, flush=True)

    results = [Result(requested_id=value, input_type=classify_id(value)) for value in ids]

    pmcid_values = [result.requested_id.upper() for result in results if result.input_type == "pmcid"]
    pmcid_lookup: dict[str, dict[str, str]] = {}
    if pmcid_values:
        print(f"  Converting {len(pmcid_values)} PMCID(s) to PMIDs...", file=sys.stderr, end="", flush=True)
        pmcid_lookup = convert_pmcids(client, pmcid_values)
        print(" done", file=sys.stderr, flush=True)

    pubmed_ids: list[str] = []
    for result in results:
        if result.input_type == "pmid":
            result.pmid = result.requested_id
            pubmed_ids.append(result.pmid)
            continue

        converted = pmcid_lookup.get(result.requested_id.upper(), {})
        result.pmcid = converted.get("pmcid", result.requested_id.upper())
        result.pmid = converted.get("pmid", "")
        result.error = converted.get("error", "")
        if result.pmid:
            pubmed_ids.append(result.pmid)
        elif not result.error:
            result.error = "PMCID could not be converted to PMID"

    disease_map: dict[str, list[DiseaseEntity]] = {}
    if pubmed_ids:
        unique_pubmed_ids = unique_preserving_order(pubmed_ids)
        print(f"  Fetching PubTator3 annotations for {len(unique_pubmed_ids)} PMID(s)...", file=sys.stderr, end="", flush=True)
        disease_map = fetch_disease_entities(client, unique_pubmed_ids)
        print(" done", file=sys.stderr, flush=True)

    for result in results:
        entities = disease_map.get(result.pmid, [])
        result.disease_names = [entity.name for entity in entities]
        result.disease_ids = [entity.mesh_id for entity in entities]
        if not entities and not result.error:
            result.error = "No disease entities found"

    found = sum(1 for r in results if r.disease_names)
    errors = sum(1 for r in results if r.error)
    suffix = f", {errors} error(s)" if errors else ""
    print(f"Done: {found}/{total} had disease annotations{suffix}", file=sys.stderr, flush=True)

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch PubTator3 disease entities for PMID/PMCID input(s).",
        epilog=(
            "Single ID prints one disease per line as name<TAB>mesh_id. Multiple IDs produce CSV with "
            "requested_id,input_type,pmid,pmcid,disease_names,disease_ids,error."
        ),
    )
    parser.add_argument(
        "ids",
        nargs="*",
        help="One or more PMIDs or PMCIDs (for example: 38243197 or PMC10797958).",
    )
    parser.add_argument(
        "-i", "--input-csv",
        metavar="FILE",
        help="Read IDs from this CSV file instead of (or in addition to) positional arguments.",
    )
    parser.add_argument(
        "--id-column",
        metavar="COLUMN",
        help="Column name to read IDs from when using --input-csv. Defaults to the first column.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write CSV output to this path. If omitted, CSV is printed to stdout for multi-ID input.",
    )
    return parser


def write_csv(results: list[Result], output_path: str | None) -> None:
    fieldnames = ["requested_id", "input_type", "pmid", "pmcid", "disease_names", "disease_ids", "error"]

    def row_for(result: Result) -> dict[str, str]:
        return {
            "requested_id": result.requested_id,
            "input_type": result.input_type,
            "pmid": result.pmid,
            "pmcid": result.pmcid,
            "disease_names": "; ".join(result.disease_names),
            "disease_ids": "; ".join(result.disease_ids),
            "error": result.error,
        }

    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(row_for(result))
        return

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for result in results:
        writer.writerow(row_for(result))
    sys.stdout.write(buffer.getvalue())


def print_single_result(result: Result) -> int:
    if result.disease_names:
        for name, mesh_id in zip(result.disease_names, result.disease_ids):
            if mesh_id:
                print(f"{name}\t{mesh_id}")
            else:
                print(name)
        return 0

    print(result.error or "No disease entities found", file=sys.stderr)
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ids = list(args.ids)
    if args.input_csv:
        try:
            csv_ids = load_ids_from_csv(args.input_csv, args.id_column)
        except (OSError, ValueError) as exc:
            print(f"Error reading CSV: {exc}", file=sys.stderr)
            return 1
        ids = csv_ids + ids

    if not ids:
        parser.error("Provide at least one ID as a positional argument or via --input-csv.")

    try:
        results = fetch_results(ids)
    except (ValueError, RuntimeError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if len(results) == 1 and not args.output:
        return print_single_result(results[0])

    write_csv(results, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
