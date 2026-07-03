#!/usr/bin/env python3
"""Fetch sample metadata for a project/study accession and write CSV.

Database is auto-detected from the accession prefix:
  ENA:      PRJEB, ERP, ERS, SAMEA  → EBI ENA APIs (XML batch, 200/req)
  CNCB-GSA: PRJCA, CRA              → CNCB browse pages (HTML) + GWH BioSample API

CNCB-GSA flow:
  CRA...  → scrape gsa/browse/CRA to get PRJCA → scrape bioproject/browse/PRJCA
            for full SAMC list → GWH API /bioSample/SAMC per sample
  PRJCA...→ scrape bioproject/browse/PRJCA for SAMC list → GWH API per sample

Examples
--------
Print CSV to stdout:
    python scripts/get_ena_project_samples.py PRJEB46665
    python scripts/get_ena_project_samples.py CRA000112
    python scripts/get_ena_project_samples.py PRJCA000246

Write CSV to a file:
    python scripts/get_ena_project_samples.py PRJEB46665 -o samples.csv
    python scripts/get_ena_project_samples.py PRJCA000246 -o samples.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict

import requests


ENA_PORTAL_SEARCH_BASE = "https://www.ebi.ac.uk/ena/portal/api/search"
ENA_BROWSER_XML_BASE = "https://www.ebi.ac.uk/ena/browser/api/xml"
CNCB_GSA_BROWSE_BASE = "https://ngdc.cncb.ac.cn/gsa/browse"
CNCB_BIOPROJECT_BROWSE_BASE = "https://ngdc.cncb.ac.cn/bioproject/browse"
GWH_API_BASE = "https://ngdc.cncb.ac.cn/gwh/api/public"
TOOL_NAME = "ena_metadata_harmonization"

DEFAULT_REQUESTS_PER_SECOND = 2.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0 / DEFAULT_REQUESTS_PER_SECOND
# CRA prefix is only 3 chars, so allow 2+ letter prefixes
PROJECT_RE = re.compile(r"^[A-Z]{2,}\d+$", re.IGNORECASE)
XML_BATCH_SIZE = 200
SAMC_RE = re.compile(r"\bSAMC\d+\b")
PRJCA_RE = re.compile(r"\bPRJCA\d+\b")

DB_PREFIXES: dict[str, str] = {
    "SAMEA": "ena",  "PRJEB": "ena", "ERP": "ena", "ERS": "ena",
    "PRJCA": "cncb", "SAMC": "cncb", "CRA": "cncb",
}

CORE_COLUMNS = [
    "project_accession",
    "sample_accession",
    "sample_alias",
    "sample_title",
    "center_name",
    "primary_id",
    "secondary_id",
    "taxon_id",
    "scientific_name",
    "description",
    "error",
]



def detect_database(project_accession: str) -> str:
    acc = project_accession.upper()
    for prefix in sorted(DB_PREFIXES, key=len, reverse=True):
        if acc.startswith(prefix):
            return DB_PREFIXES[prefix]
    return "ena"


class ENAClient:
    def __init__(self, tool: str = TOOL_NAME) -> None:
        self.tool = tool
        self._last_request_time = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        self._throttle()
        merged_headers = {"User-Agent": self.tool}
        if headers:
            merged_headers.update(headers)
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = exc.response.text if exc.response is not None else ""
            raise RuntimeError(f"HTTP error for {response.url}: {detail}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Request failed for {url}: {exc}") from exc

        self._last_request_time = time.monotonic()
        return response

    # ── ENA ──────────────────────────────────────────────────────────────────

    def fetch_sample_accessions(self, project_accession: str) -> list[str]:
        response = self._get(
            ENA_PORTAL_SEARCH_BASE,
            {
                "result": "sample",
                "query": f'study_accession="{project_accession}"',
                "fields": "sample_accession",
                "format": "json",
                "limit": "0",
            },
        )
        records = response.json()
        return [str(r.get("sample_accession", "")).strip() for r in records if r.get("sample_accession")]

    def fetch_samples_xml_batch(self, sample_accessions: list[str]) -> str:
        response = self._get(f"{ENA_BROWSER_XML_BASE}/{','.join(sample_accessions)}")
        return response.text

    # ── CNCB-GSA ─────────────────────────────────────────────────────────────

    def fetch_cncb_prjca_from_cra(self, cra_accession: str) -> str:
        """Resolve a CRA accession to its PRJCA via the GSA browse page."""
        response = self._get(
            f"{CNCB_GSA_BROWSE_BASE}/{cra_accession}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        matches = PRJCA_RE.findall(response.text)
        if not matches:
            raise RuntimeError(
                f"Could not find a PRJCA accession on the browse page for {cra_accession}."
            )
        return matches[0]

    def fetch_cncb_samc_accessions(self, prjca_accession: str) -> list[str]:
        """Scrape the CNCB BioProject browse page to get all linked SAMC accessions."""
        response = self._get(
            f"{CNCB_BIOPROJECT_BROWSE_BASE}/{prjca_accession}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return list(dict.fromkeys(SAMC_RE.findall(response.text)))

    def fetch_gwh_biosample(self, samc_accession: str) -> dict:
        """Fetch BioSample attributes from the CNCB GWH API."""
        response = self._get(f"{GWH_API_BASE}/bioSample/{samc_accession}")
        return response.json()


# ── Column helpers ────────────────────────────────────────────────────────────


def normalize_column_name(raw_name: str) -> str:
    normalized = raw_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = normalized.strip("_")
    return normalized or "unnamed_field"


def add_value(row: dict[str, str], column_name: str, value: str) -> None:
    clean_value = " ".join(value.split())
    if not clean_value:
        return
    existing = row.get(column_name, "")
    if not existing:
        row[column_name] = clean_value
        return
    existing_parts = existing.split("; ")
    if clean_value not in existing_parts:
        row[column_name] = f"{existing}; {clean_value}"


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def assign_dynamic_column(
    raw_tag: str,
    value: str,
    row: dict[str, str],
    tag_to_column: OrderedDict[str, str],
    column_to_tag: dict[str, str],
) -> None:
    if not raw_tag.strip():
        return
    if raw_tag not in tag_to_column:
        base = normalize_column_name(raw_tag)
        candidate = base
        suffix = 2
        while candidate in column_to_tag and column_to_tag[candidate] != raw_tag:
            candidate = f"{base}_{suffix}"
            suffix += 1
        tag_to_column[raw_tag] = candidate
        column_to_tag[candidate] = raw_tag
    add_value(row, tag_to_column[raw_tag], value)


# ── ENA parsing ──────────────────────────────────────────────────────────────


def parse_sample_element(
    project_accession: str,
    sample: ET.Element,
    fallback_accession: str,
    tag_to_column: OrderedDict[str, str],
    column_to_tag: dict[str, str],
) -> dict[str, str]:
    row: dict[str, str] = {
        "project_accession": project_accession,
        "sample_accession": sample.get("accession", fallback_accession),
        "sample_alias": sample.get("alias", ""),
        "center_name": sample.get("center_name", ""),
        "sample_title": sample.findtext("./TITLE", default="").strip(),
        "primary_id": sample.findtext("./IDENTIFIERS/PRIMARY_ID", default="").strip(),
        "secondary_id": sample.findtext("./IDENTIFIERS/SECONDARY_ID", default="").strip(),
        "taxon_id": sample.findtext("./SAMPLE_NAME/TAXON_ID", default="").strip(),
        "scientific_name": sample.findtext("./SAMPLE_NAME/SCIENTIFIC_NAME", default="").strip(),
        "description": sample.findtext("./DESCRIPTION", default="").strip(),
        "error": "",
    }
    for sample_attribute in sample.findall("./SAMPLE_ATTRIBUTES/SAMPLE_ATTRIBUTE"):
        raw_tag = sample_attribute.findtext("./TAG", default="")
        value = sample_attribute.findtext("./VALUE", default="")
        assign_dynamic_column(raw_tag, value, row, tag_to_column, column_to_tag)
    return row


# ── CNCB-GSA / GWH parsing ───────────────────────────────────────────────────

# Fields inside sampleAttribute that are internal bookkeeping, not biology
_GWH_SKIP_ATTR_KEYS = {"sample", "attributeId", "taxon"}


def parse_gwh_biosample(
    project_accession: str,
    data: dict,
    samc_accession: str,
    tag_to_column: OrderedDict[str, str],
    column_to_tag: dict[str, str],
) -> dict[str, str]:
    taxon = data.get("taxon") or {}
    sample_attr = data.get("sampleAttribute") or {}
    attr_taxon = sample_attr.get("taxon") or {}

    taxon_id = str(taxon.get("taxonId", "") or attr_taxon.get("taxonId", "") or "")
    sci_name = taxon.get("name", "") or attr_taxon.get("name", "") or ""

    row: dict[str, str] = {
        "project_accession": project_accession,
        "sample_accession": data.get("accession", samc_accession),
        "sample_alias": data.get("name", ""),
        "sample_title": data.get("title", "") or data.get("name", ""),
        "center_name": "",
        "primary_id": data.get("accession", samc_accession),
        "secondary_id": "",
        "taxon_id": taxon_id,
        "scientific_name": sci_name,
        "description": data.get("description", "") or "",
        "error": "",
    }

    # Flatten all sampleAttribute fields as dynamic columns
    for key, val in sample_attr.items():
        if key in _GWH_SKIP_ATTR_KEYS or val is None or val == "":
            continue
        # sex is stored as int (1=male, 2=female) in some sample types
        if key == "sex":
            val = {1: "male", 2: "female"}.get(val, str(val))
        assign_dynamic_column(key, str(val), row, tag_to_column, column_to_tag)

    return row


# ── Per-database fetch orchestration ─────────────────────────────────────────


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def _fetch_ena_rows(
    client: ENAClient,
    project_accession: str,
    max_samples: int | None,
    tag_to_column: OrderedDict[str, str],
    column_to_tag: dict[str, str],
) -> list[dict[str, str]]:
    sample_accessions = unique_preserving_order(client.fetch_sample_accessions(project_accession))
    if not sample_accessions:
        raise RuntimeError(f"No sample accessions found for project {project_accession}")
    if max_samples is not None:
        sample_accessions = sample_accessions[:max_samples]

    total = len(sample_accessions)
    batches = chunked(sample_accessions, XML_BATCH_SIZE)
    print(f"  Found {total} sample(s), fetching in {len(batches)} batch(es).", file=sys.stderr, flush=True)

    rows: list[dict[str, str]] = []
    for batch_i, batch in enumerate(batches, 1):
        start = (batch_i - 1) * XML_BATCH_SIZE + 1
        end = start + len(batch) - 1
        print(f"  Batch [{batch_i}/{len(batches)}] samples {start}–{end}...", file=sys.stderr, end="", flush=True)
        try:
            batch_xml = client.fetch_samples_xml_batch(batch)
            root = ET.fromstring(batch_xml)
            sample_elements = root.findall("./SAMPLE")
            by_accession = {el.get("accession", ""): el for el in sample_elements}
            print(f" got {len(sample_elements)}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f" error: {exc}", file=sys.stderr, flush=True)
            for acc in batch:
                rows.append({"project_accession": project_accession, "sample_accession": acc, "error": str(exc)})
            continue

        for acc in batch:
            sample_el = by_accession.get(acc)
            if sample_el is None:
                rows.append({"project_accession": project_accession, "sample_accession": acc, "error": "not returned in batch XML"})
            else:
                rows.append(parse_sample_element(project_accession, sample_el, acc, tag_to_column, column_to_tag))

    errors = sum(1 for r in rows if r.get("error"))
    suffix = f", {errors} error(s)" if errors else ""
    print(f"Done: {total - errors}/{total} samples fetched{suffix}", file=sys.stderr, flush=True)
    return rows


def _fetch_cncb_rows(
    client: ENAClient,
    project_accession: str,
    max_samples: int | None,
    tag_to_column: OrderedDict[str, str],
    column_to_tag: dict[str, str],
) -> list[dict[str, str]]:
    # Resolve CRA → PRJCA so we can get the full sample list from BioProject page
    if project_accession.upper().startswith("CRA"):
        print(f"  Resolving {project_accession} to PRJCA...", file=sys.stderr, flush=True)
        prjca = client.fetch_cncb_prjca_from_cra(project_accession)
        print(f"  Found: {prjca}", file=sys.stderr, flush=True)
    else:
        prjca = project_accession

    print(f"  Scraping SAMC accessions from BioProject page ({prjca})...", file=sys.stderr, flush=True)
    samc_list = client.fetch_cncb_samc_accessions(prjca)
    if not samc_list:
        raise RuntimeError(f"No SAMC accessions found on BioProject page for {prjca}")
    if max_samples is not None:
        samc_list = samc_list[:max_samples]

    total = len(samc_list)
    print(f"  Found {total} sample(s), fetching via GWH API...", file=sys.stderr, flush=True)

    rows: list[dict[str, str]] = []
    for i, samc in enumerate(samc_list, 1):
        print(f"  [{i}/{total}] {samc}...", file=sys.stderr, end="", flush=True)
        try:
            data = client.fetch_gwh_biosample(samc)
            if data.get("message") != "SUCCESS":
                raise RuntimeError(f"GWH API returned: {data.get('message')}")
            rows.append(parse_gwh_biosample(project_accession, data, samc, tag_to_column, column_to_tag))
            print(" ok", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f" error: {exc}", file=sys.stderr, flush=True)
            rows.append({"project_accession": project_accession, "sample_accession": samc, "error": str(exc)})

    errors = sum(1 for r in rows if r.get("error"))
    suffix = f", {errors} error(s)" if errors else ""
    print(f"Done: {total - errors}/{total} samples fetched{suffix}", file=sys.stderr, flush=True)
    return rows


# ── Public API ────────────────────────────────────────────────────────────────


def fetch_rows(project_accession: str, max_samples: int | None = None) -> tuple[list[dict[str, str]], list[str]]:
    client = ENAClient()
    database = detect_database(project_accession)
    print(f"Fetching samples for {project_accession} (source: {database.upper()})...", file=sys.stderr, flush=True)

    tag_to_column: OrderedDict[str, str] = OrderedDict()
    column_to_tag: dict[str, str] = {}

    if database == "cncb":
        rows = _fetch_cncb_rows(client, project_accession, max_samples, tag_to_column, column_to_tag)
    else:
        rows = _fetch_ena_rows(client, project_accession, max_samples, tag_to_column, column_to_tag)

    columns = CORE_COLUMNS + [column for column in tag_to_column.values() if column not in CORE_COLUMNS]
    return rows, columns


def write_csv(rows: list[dict[str, str]], columns: list[str], output_path: str | None) -> None:
    if output_path:
        with open(output_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        return

    writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch sample metadata for a project/study accession and flatten to CSV. "
            "Database is auto-detected: ENA (PRJEB/ERP) or CNCB-GSA (PRJCA/CRA)."
        ),
    )
    parser.add_argument(
        "project_accession",
        help="Project/study accession, e.g. PRJEB46665, CRA000112, PRJCA000246.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write CSV to this path. If omitted, CSV is printed to stdout.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        help="Only fetch the first N samples. Useful for quick tests on large studies.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_accession = args.project_accession.strip().upper()

    if not PROJECT_RE.fullmatch(project_accession):
        print(f"Error: invalid project accession: {args.project_accession!r}", file=sys.stderr)
        return 1
    if args.max_samples is not None and args.max_samples <= 0:
        print("Error: --max-samples must be a positive integer", file=sys.stderr)
        return 1

    try:
        rows, columns = fetch_rows(project_accession, max_samples=args.max_samples)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    write_csv(rows, columns, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
