#!/usr/bin/env python3
"""Save collector NDJSON as complete, verified official replay files.

Only durableGameIds in the JSON result may be acknowledged to the collector.
Any malformed response or HTTP failure stops the batch without retries.
"""
import argparse
import base64
import binascii
import json
from pathlib import Path
import re
import sys
import urllib.error

import policy_official_archive as archive


CLIENT_VERSION = re.compile(r"(?:web-\d+(?:\.\d+)+|WebGL_2022-\d+\.\d+\.\d+)\Z")
MAX_LINE_BYTES = ((archive.MAX_BYTES + 2) // 3) * 4 + 4096


def decode_item(line):
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("Collector NDJSON line exceeds the response size limit")
    item = json.loads(line)
    if not isinstance(item, dict):
        raise ValueError("Collector NDJSON row must be an object")
    archive.valid_identifier(item.get("gameId"))
    version = item.get("clientVersion")
    if not isinstance(version, str) or not CLIENT_VERSION.fullmatch(version):
        raise ValueError("Collector row requires an explicit official web client version")
    size, code, encoded = item.get("responseBytes"), item.get("serverCode"), item.get("wsResponseBase64")
    if type(size) is not int or not 3 <= size <= archive.MAX_BYTES:
        raise ValueError("Collector responseBytes must be within the response size limit")
    if type(code) is not int or code < 0:
        raise ValueError("Collector serverCode must be a nonnegative integer")
    if not isinstance(encoded, str):
        raise ValueError("Collector wsResponseBase64 must be a string")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Collector response has invalid base64") from error
    if len(raw) != size or base64.b64encode(raw).decode("ascii") != encoded:
        raise ValueError("Collector response length or canonical base64 differs")
    return item, raw


def save_item(line, store, fetch_data_urls=False):
    item, raw = decode_item(line)
    payload = archive.fetch.load_payload(raw, "ws-response", store.decoder)
    code = payload.get("error", {}).get("code", 0)
    if code != item["serverCode"]:
        raise ValueError("Collector serverCode differs from the original response")
    if code:
        raise archive.StopCollection(f"fetchGameRecord error {code}; collection must stop")
    if payload.get("head", {}).get("uuid") != item["gameId"]:
        raise ValueError("Response UUID differs from requested UUID")
    body, url = None, None
    if not payload.get("data"):
        url = payload.get("data_url", "")
        archive.trusted_data_url(url)
        previous = store.games.get(item["gameId"])
        if previous:
            body = (store.output / previous["files"]["data"]["path"]).read_bytes()
        elif fetch_data_urls:
            body = archive.download_data_url(url)
        else:
            raise ValueError("Response needs its original data_url body; use --fetch-data-urls explicitly")
    return store.add(raw, fmt="ws-response", expected_uuid=item["gameId"],
                     data_url_body=body, body_url=url)


def ingest(stream, store, fetch_data_urls=False):
    result = {"status": "complete", "processedResponses": 0, "savedGames": 0,
              "duplicateGames": 0, "uniqueGames": store.count, "durableGameIds": []}
    number = 0
    while True:
        line = stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            return result
        number += 1
        try:
            saved = save_item(line, store, fetch_data_urls)
        except (ValueError, OSError, KeyError, TypeError, archive.StopCollection, urllib.error.URLError) as error:
            result.update(status="stopped", failedLine=number, error=str(error))
            return result
        result["processedResponses"] += 1
        result["savedGames" if saved["status"] == "saved" else "duplicateGames"] += 1
        result["uniqueGames"] = store.count
        if saved["gameId"] not in result["durableGameIds"]:
            result["durableGameIds"].append(saved["gameId"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch-data-urls", action="store_true",
                        help="Fetch missing bodies only from the fixed official replay origin")
    args = parser.parse_args()
    try:
        store = archive.OfficialArchive(args.output, args.schema.read_bytes())
        with args.input.open("rb") as stream:
            result = ingest(stream, store, args.fetch_data_urls)
    except (ValueError, OSError, KeyError, TypeError, archive.StopCollection) as error:
        result = {"status": "stopped", "durableGameIds": [], "error": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    sys.exit(main())
