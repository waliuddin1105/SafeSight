"""Generate the API contract from registered routes and public storage fields."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import Boolean, Integer, Float, DateTime, JSON
from safesight.config import ROOT
from safesight.storage.schema import Base


def build(app) -> dict:
    """Describe actual API routes, CSRF/cookie security and public resource schemas."""
    resources = {}
    hidden = {"password_hash", "path", "config", "worker_id", "access_token", "refresh_token"}
    excluded = {"auth_sessions", "login_attempts", "runtime_snapshots"}
    for table in Base.metadata.tables.values():
        if table.name in excluded:
            continue
        properties = {}
        for column in table.columns:
            if column.name in hidden:
                continue
            kind = (
                "boolean"
                if isinstance(column.type, Boolean)
                else "integer"
                if isinstance(column.type, Integer)
                else "number"
                if isinstance(column.type, Float)
                else "object"
                if isinstance(column.type, JSON)
                else "string"
            )
            schema = {"type": [kind, "null"] if column.nullable else kind}
            if isinstance(column.type, DateTime):
                schema["format"] = "date-time"
            if column.name in ("enabled_models", "predictions"):
                schema = {"type": "array", "items": {"type": "string" if column.name == "enabled_models" else "object"}}
            properties[column.name] = schema
        if table.name == "evidence":
            properties["url"] = {"type": ["string", "null"]}
        resources[table.name] = {"type": "object", "properties": properties, "required": list(properties)}
    paths = {}
    public = {
        "/api/v1/auth/me",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/v1"):
            continue
        path = re.sub(r"<([^>]+)>", r"{\1}", rule.rule)
        operations = {}
        for method in sorted(rule.methods - {"OPTIONS", "HEAD"}):
            parameters = [
                {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
                for name in sorted(rule.arguments)
            ]
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                parameters.append(
                    {"name": "X-CSRF-Token", "in": "header", "required": True, "schema": {"type": "string"}}
                )
            operation = {
                "operationId": rule.endpoint.replace(".", "_") + "_" + method.lower(),
                "summary": rule.endpoint.replace(".", " "),
                "parameters": parameters,
                "security": [] if rule.rule in public else [{"sessionCookie": []}],
                "responses": {
                    "200": {"description": "Successful response"},
                    "400": {"description": "Invalid input"},
                    "401": {"description": "Sign-in required"},
                    "403": {"description": "Permission or CSRF failure"},
                    "503": {"description": "Dependency unavailable"},
                },
            }
            segment = path.split("/")[3]
            segment = {"jobs": "processing_jobs"}.get(segment, segment)
            if segment in resources and method == "GET" and len(path.split("/")) <= 5:
                schema = {"$ref": f"#/components/schemas/{segment}"}
                if not rule.arguments:
                    schema = {
                        "type": "object",
                        "properties": {"items": {"type": "array", "items": schema}},
                        "required": ["items"],
                    }
                operation["responses"]["200"]["content"] = {"application/json": {"schema": schema}}
            if path.endswith("/auth/login"):
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "password"],
                                "properties": {
                                    "email": {"type": "string", "format": "email"},
                                    "password": {"type": "string", "writeOnly": True},
                                },
                            }
                        }
                    },
                }
            if path.endswith("/uploads"):
                operation["responses"]["202"] = {"description": "Recording queued with pinned model snapshot"}
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file", "source_id"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                    "source_id": {"type": "string"},
                                    "models": {"type": "string", "description": "JSON array of model slugs"},
                                    "versions": {
                                        "type": "string",
                                        "description": "JSON object mapping slugs to run IDs",
                                    },
                                    "evaluation": {"type": "boolean"},
                                    "captured_at": {"type": "string", "format": "date-time"},
                                    "ground_truth": {"type": "string", "description": "Optional JSON object with events: slug, subtype, start/end seconds and normalized xyxy box"},
                                },
                            }
                        }
                    },
                }
            operations[method.lower()] = operation
        paths[path] = operations
    return {
        "openapi": "3.1.0",
        "info": {"title": "SafeSight REST API", "version": "1.1.0"},
        "paths": paths,
        "components": {
            "securitySchemes": {"sessionCookie": {"type": "apiKey", "in": "cookie", "name": "session"}},
            "schemas": resources,
        },
    }


def main() -> int:
    from safesight.backend.app import create_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app = create_app()
    output = json.dumps(build(app), indent=2, sort_keys=True) + "\n"
    path = ROOT / "docs/openapi.json"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != output:
            raise SystemExit("OpenAPI contract is stale")
    else:
        path.write_text(output, encoding="utf-8")
    app.extensions["db_engine"].dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
