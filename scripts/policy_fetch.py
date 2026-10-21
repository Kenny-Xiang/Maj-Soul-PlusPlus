#!/usr/bin/env python3
"""Import public/local Mahjong Soul replays without accounts or credentials.

Only explicit URLs are fetched. JSON exports need no dependencies; binary
protobuf imports use the pinned public client schema and a small wire decoder.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request
from urllib.parse import urlparse


SCHEMA_URL = "https://game.maj-soul.com/1/v0.11.243.w/res/proto/liqi.json"
SCHEMA_SHA256 = "f2955c3d10cf2d42bee9309f672c062540941ea0cffe1bd62e3f436c7afc404c"
MAX_BYTES = 16 * 1024 * 1024
PUBLIC_SAMPLES = {
    "four-player-210815": {
        "url": "https://raw.githubusercontent.com/Fat-pig-Cui/misc-code/198741f373edbf5dabe4dc6c7ce66305d5be43a6/paipu/paipu_210815-6da08e40-2605-42fb-a5e3-f8aa5940362a.json",
        "sha256": "dfee868402e7f875a8eb21b39fbb5df6753ae2803362f84f0aa518c6b16d47a3",
        "size": 765156,
        "license": "MIT (upstream repository; see docs/policy-data-sources.md)",
        "kind": "public-third-party-export-of-official-replay",
    },
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect refused; explicitly provide the final URL")


def download(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("An explicit HTTPS URL without credentials is required")
    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(url, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Download exceeds the 16 MiB single-replay limit")
    return data


def read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("Protobuf varint exceeds 64 bits")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Invalid protobuf varint")


def read_wire(data, offset, wire):
    if wire == 0:
        return read_varint(data, offset)
    if wire == 2:
        size, offset = read_varint(data, offset)
    elif wire in (1, 5):
        size = 8 if wire == 1 else 4
    else:
        raise ValueError(f"Unsupported protobuf wire type {wire}")
    end = offset + size
    if end > len(data):
        raise ValueError("Truncated protobuf field")
    return data[offset:end], end


class SchemaDecoder:
    """Decode protobufjs JSON while preserving absent-field presence."""

    def __init__(self, schema):
        self.types = {}
        self.unknown_fields = set()

        def visit(node, prefix=""):
            for name, child in node.get("nested", {}).items():
                full = f"{prefix}.{name}" if prefix else name
                self.types[full] = child
                visit(child, full)

        visit(schema)

    def resolve(self, name, scope):
        if name.startswith("."):
            return name[1:]
        parent = scope
        while parent:
            full = f"{parent}.{name}"
            if full in self.types:
                return full
            parent = parent.rpartition(".")[0]
        if name in self.types:
            return name
        raise ValueError(f"Unknown schema type {name} in {scope}")

    def scalar(self, kind, raw, wire, scope, depth):
        if kind in ("string", "bytes"):
            if wire != 2:
                raise ValueError(f"Invalid wire type for {kind}")
            return raw.decode("utf-8") if kind == "string" else raw
        formats = {"double": (1, "<d"), "float": (5, "<f"),
                   "fixed32": (5, "<I"), "sfixed32": (5, "<i"),
                   "fixed64": (1, "<Q"), "sfixed64": (1, "<q")}
        if kind in formats:
            expected, fmt = formats[kind]
            if wire != expected:
                raise ValueError(f"Invalid wire type for {kind}")
            return struct.unpack(fmt, raw)[0]
        if kind in ("bool", "uint32", "uint64", "int32", "int64", "sint32", "sint64"):
            if wire != 0:
                raise ValueError(f"Invalid wire type for {kind}")
            if kind == "bool":
                return bool(raw)
            if kind.startswith("sint"):
                return (raw >> 1) ^ -(raw & 1)
            bits = 32 if kind.endswith("32") else 64
            raw &= (1 << bits) - 1
            return raw - (1 << bits) if kind.startswith("int") and raw >> (bits - 1) else raw
        full = self.resolve(kind, scope)
        if "values" in self.types[full]:
            if wire != 0:
                raise ValueError("Invalid enum wire type")
            return raw
        if wire != 2:
            raise ValueError("Invalid message wire type")
        return self.decode(full, raw, depth + 1)

    def decode(self, name, data, depth=0):
        if depth > 64:
            raise ValueError("Protobuf nesting exceeds 64 levels")
        full = name.lstrip(".")
        if full not in self.types or "fields" not in self.types[full]:
            raise ValueError(f"Unknown protobuf message {name}")
        fields = {f["id"]: (key, f) for key, f in self.types[full]["fields"].items()}
        output, offset = {}, 0
        while offset < len(data):
            tag, offset = read_varint(data, offset)
            field_id, wire = tag >> 3, tag & 7
            if field_id == 0:
                raise ValueError("Invalid protobuf field zero")
            raw, offset = read_wire(data, offset, wire)
            if field_id not in fields:
                self.unknown_fields.add(f"{full}:{field_id}")
                continue
            key, field = fields[field_id]
            kind = field["type"]
            packed_wire = {"double": 1, "fixed64": 1, "sfixed64": 1,
                           "float": 5, "fixed32": 5, "sfixed32": 5}.get(kind, 0)
            is_number = kind in ("bool", "uint32", "uint64", "int32", "int64", "sint32", "sint64", "double", "float", "fixed32", "fixed64", "sfixed32", "sfixed64")
            if field.get("rule") == "repeated" and wire == 2 and is_number:
                values, pos = [], 0
                while pos < len(raw):
                    item, pos = read_wire(raw, pos, packed_wire)
                    values.append(self.scalar(kind, item, packed_wire, full, depth))
                output.setdefault(key, []).extend(values)
            else:
                value = self.scalar(kind, raw, wire, full, depth)
                if field.get("rule") == "repeated":
                    output.setdefault(key, []).append(value)
                else:
                    output[key] = value
        return output


def as_bytes(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return base64.b64decode(value, validate=True)
    if isinstance(value, list):
        return bytes(value)
    if isinstance(value, dict) and value.get("type") == "Buffer":
        return bytes(value["data"])
    raise ValueError("Expected bytes, base64, or a byte array")


def unwrap(value, decoder):
    if not isinstance(value, dict):
        if decoder is None:
            raise ValueError("Binary input requires --schema or --fetch-schema")
        value = decoder.decode("lq.Wrapper", as_bytes(value))
    name = value.get("name", "").removeprefix(".lq.").removeprefix("lq.")
    data = value.get("data", {})
    if not isinstance(data, dict):
        if decoder is None:
            raise ValueError("Binary input requires --schema or --fetch-schema")
        data = decoder.decode(f"lq.{name}", as_bytes(data))
    return {"name": name, "data": data}


def normalize(payload, decoder=None, game_id=None):
    """Normalize decoded ResGameRecord, GameDetailRecords, or record arrays.

    User requests belong to the preceding result's response window. Requests
    preceding the first result are retained separately, not assigned forward.
    """
    head = payload.get("head", {}) if isinstance(payload, dict) else {}
    if isinstance(payload, dict) and payload.get("error", {}).get("code", 0):
        raise ValueError(f"fetchGameRecord error {payload['error']['code']}")
    detail = payload
    if isinstance(payload, dict) and "data" in payload:
        if not payload["data"]:
            if payload.get("data_url"):
                raise ValueError("data_url is not followed implicitly; pass --data-url explicitly")
            raise ValueError("Replay response has no data")
        detail = unwrap(payload if "name" in payload else payload["data"], decoder)
        if detail["name"] != "GameDetailRecords":
            raise ValueError(f"Expected GameDetailRecords, got {detail['name']}")
        detail = detail["data"]
    records, initial_inputs = [], []
    if isinstance(detail, dict) and "actions" in detail:
        if detail.get("version", 210715) != 210715:
            raise ValueError(f"Unsupported action record version {detail.get('version')}")
        for index, action in enumerate(detail["actions"]):
            if action.get("type") == 1 and not action.get("result"):
                raise ValueError(f"Result action {index} has no result; replay may be truncated")
            if action.get("result"):
                record = unwrap(action["result"], decoder)
                record["sourceActionIndex"] = index
                records.append(record)
            if "user_input" in action:
                user_input = dict(action["user_input"])
                user_input["_actionIndex"] = index
                if "passed" in action:
                    user_input["_passed"] = action["passed"]
                if records:
                    records[-1].setdefault("userInputs", []).append(user_input)
                else:
                    initial_inputs.append(user_input)
    else:
        entries = detail if isinstance(detail, list) else detail.get("records", detail.get("details", []))
        for entry in entries:
            record = unwrap(entry, decoder)
            if isinstance(entry, dict) and "userInputs" in entry:
                record["userInputs"] = entry["userInputs"]
            records.append(record)
    if not records or any(not r["name"].startswith("Record") for r in records):
        raise ValueError("No valid Record* replay stream found")
    identifiers = {value for value in (game_id, payload.get("gameId") if isinstance(payload, dict) else None,
                                      head.get("uuid")) if value}
    if len(identifiers) > 1:
        raise ValueError("Conflicting game UUIDs; do not relabel one match for a different split")
    if not identifiers:
        raise ValueError("Replay has no game UUID; supply --game-id for grouping")
    identifier = identifiers.pop()
    if not isinstance(identifier, str):
        raise ValueError("Game UUID must be a string")
    return {"gameId": identifier, "head": head, "records": records,
            "initialUserInputs": initial_inputs}


def load_payload(data, fmt, decoder):
    if fmt == "auto":
        fmt = "json" if data.lstrip().startswith((b"{", b"[")) else "wrapper"
    if fmt == "json":
        return json.loads(data)
    if decoder is None:
        raise ValueError("Binary input requires --schema or --fetch-schema")
    if fmt == "ws-response":
        if len(data) < 3 or data[0] != 3:
            raise ValueError("Expected response frame (03 + uint16 request id)")
        frame = decoder.decode("lq.Wrapper", data[3:])
        return decoder.decode("lq.ResGameRecord", frame.get("data", b""))
    if fmt == "response":
        return decoder.decode("lq.ResGameRecord", data)
    if fmt == "detail":
        return decoder.decode("lq.GameDetailRecords", data)
    return {"data": data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--url", help="Explicit raw replay or JSON URL; never a login")
    inputs.add_argument("--public-sample", choices=PUBLIC_SAMPLES)
    parser.add_argument("--format", choices=("auto", "json", "wrapper", "response", "ws-response", "detail"), default="auto")
    parser.add_argument("--data-url", help="Explicit authorization to read a response's matching data_url")
    parser.add_argument("--schema", type=Path, help="Pinned liqi.json; SHA-256 must match")
    parser.add_argument("--fetch-schema", action="store_true", help="Download the pinned public client schema")
    parser.add_argument("--game-id", help="Required if the input has no head.uuid")
    parser.add_argument("--head-json", type=Path, help="Local RecordGame header for a headless binary/detail input")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".local/policy-data"))
    args = parser.parse_args(argv)
    try:
        decoder = None
        if args.schema or args.fetch_schema:
            schema_bytes = args.schema.read_bytes() if args.schema else download(SCHEMA_URL)
            if sha256(schema_bytes) != SCHEMA_SHA256:
                raise ValueError("Schema SHA-256 differs from the pinned version")
            decoder = SchemaDecoder(json.loads(schema_bytes))
            if args.fetch_schema:
                args.cache_dir.mkdir(parents=True, exist_ok=True)
                (args.cache_dir / "liqi-0.11.243.w.json").write_bytes(schema_bytes)
        source = {"kind": "local-user-input"}
        if args.public_sample:
            sample = PUBLIC_SAMPLES[args.public_sample]
            data = download(sample["url"])
            if len(data) != sample["size"] or sha256(data) != sample["sha256"]:
                raise ValueError("Public sample size or SHA-256 mismatch")
            source.update(sample)
            args.cache_dir.mkdir(parents=True, exist_ok=True)
            (args.cache_dir / f"{args.public_sample}.source.json").write_bytes(data)
        elif args.url:
            data = download(args.url)
            source.update(kind="explicit-url", url=args.url)
        else:
            data = args.input.read_bytes()
            source["path"] = str(args.input)
        if len(data) > MAX_BYTES:
            raise ValueError("Input exceeds the 16 MiB single-replay limit")
        source.update(size=len(data), sha256=sha256(data))
        payload = load_payload(data, args.format, decoder)
        if args.head_json:
            head_bytes = args.head_json.read_bytes()
            head = json.loads(head_bytes)
            if not isinstance(head, dict):
                raise ValueError("--head-json must contain a RecordGame object")
            if isinstance(payload, list):
                payload = {"records": payload}
            if payload.get("head") and payload["head"] != head:
                raise ValueError("--head-json disagrees with the existing header")
            payload["head"] = head
            source["head"] = {"path": str(args.head_json), "sha256": sha256(head_bytes)}
        if args.data_url:
            if not isinstance(payload, dict) or payload.get("data_url") != args.data_url:
                raise ValueError("--data-url must exactly match this response's data_url")
            fetched = download(args.data_url)
            payload["data"] = fetched
            source["dataUrl"] = {"url": args.data_url, "size": len(fetched), "sha256": sha256(fetched)}
        result = normalize(payload, decoder, args.game_id)
        if decoder:
            source["schema"] = {"url": SCHEMA_URL, "sha256": SCHEMA_SHA256}
            source["unknownFields"] = sorted(decoder.unknown_fields)
        result["source"] = source
        encoded = json.dumps(result, ensure_ascii=False, indent=2,
                             default=lambda x: base64.b64encode(x).decode("ascii")) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({"gameId": result["gameId"], "records": len(result["records"]),
                          "userInputs": sum(len(r.get("userInputs", [])) for r in result["records"]),
                          "output": str(args.output), "sourceSha256": source["sha256"]}))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"policy_fetch: {error}\n")


if __name__ == "__main__":
    main()
