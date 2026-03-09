#!/usr/bin/env python3
"""Serve an interactive review page for spec audit findings.

Usage:
    python serve_review.py <path-to-audit.json> [--port PORT] [--static <output.html>]
    python serve_review.py --history <audit-history-dir> [--port PORT]

Reads audit.json, embeds findings into a self-contained HTML page, and serves
it via a local HTTP server. User responses are saved to responses.json in the
same directory as audit.json.

When given --history or an audit-history directory, serves the history browser
with all past audits.

No dependencies beyond the Python stdlib.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


def load_audit(audit_path: Path) -> dict:
    """Load and validate the audit JSON file."""
    if not audit_path.exists():
        print(f"Error: {audit_path} not found", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(audit_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {audit_path}: {e}", file=sys.stderr)
        sys.exit(1)
    if "findings" not in data:
        print(f"Error: audit.json missing 'findings' key", file=sys.stderr)
        sys.exit(1)
    return data


def load_history(history_dir: Path) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """Load history index and all audits/responses from a history directory.

    Returns (index, audits_by_id, responses_by_id).
    """
    index_path = history_dir / "index.json"
    if not index_path.exists():
        print(f"Error: {index_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        index = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {index_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Sort by ID (YYYYMMDD-HHMMSS) descending so most recent is first
    index.sort(key=lambda e: e.get("id", ""), reverse=True)

    audits = {}
    responses = {}
    for entry in index:
        audit_id = entry["id"]
        audit_file = history_dir / audit_id / "audit.json"
        if audit_file.exists():
            try:
                audits[audit_id] = json.loads(audit_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        resp_file = history_dir / audit_id / "responses.json"
        if resp_file.exists():
            try:
                responses[audit_id] = json.loads(resp_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    return index, audits, responses


def generate_html(audit_data: dict, existing_responses: dict | None = None,
                  history_index: list | None = None,
                  all_audits: dict | None = None,
                  all_responses: dict | None = None) -> str:
    """Generate the complete standalone HTML page with embedded audit data."""
    template_path = Path(__file__).parent / "review.html"
    template = template_path.read_text()

    embedded = {
        "audit": audit_data,
        "existing_responses": existing_responses or {},
        "history_index": history_index,
        "all_audits": all_audits,
        "all_responses": all_responses,
    }
    data_json = json.dumps(embedded)
    return template.replace("/*__EMBEDDED_DATA__*/", f"const EMBEDDED_DATA = {data_json};")


def _port_in_use(port: int) -> bool:
    """Check if a process is already listening on the given port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split("\n"):
            if pid_str.strip():
                try:
                    os.kill(int(pid_str.strip()), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
        if result.stdout.strip():
            time.sleep(0.5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _update_index_status(history_dir: Path, audit_id: str, status: str) -> None:
    """Update the status of an audit in index.json."""
    index_path = history_dir / "index.json"
    if not index_path.exists():
        return
    try:
        index = json.loads(index_path.read_text())
        for entry in index:
            if entry["id"] == audit_id:
                entry["status"] = status
                break
        index_path.write_text(json.dumps(index, indent=2) + "\n")
    except (json.JSONDecodeError, OSError, KeyError):
        pass


class ReviewHandler(BaseHTTPRequestHandler):
    """Serves the review HTML and handles response saves."""

    def __init__(self, html_content: str, responses_path: Path,
                 history_dir: Path | None, *args, **kwargs):
        self.html_content = html_content
        self.responses_path = responses_path
        self.history_dir = history_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            content = self.html_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/api/responses":
            data = b"{}"
            if self.responses_path.exists():
                data = self.responses_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/responses":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)

                # If history mode, determine which audit's responses to save
                audit_id = data.get("audit_id")
                if self.history_dir and audit_id:
                    resp_path = self.history_dir / audit_id / "responses.json"
                    resp_path.write_text(json.dumps(data, indent=2) + "\n")
                    # Update index status if submission is complete
                    if data.get("status") == "complete":
                        _update_index_status(self.history_dir, audit_id, "complete")
                else:
                    self.responses_path.write_text(json.dumps(data, indent=2) + "\n")

                resp = b'{"ok":true}'
                self.send_response(200)
            except (json.JSONDecodeError, OSError, ValueError) as e:
                resp = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve spec audit review page")
    parser.add_argument("audit_file", type=Path, nargs="?", default=None,
                        help="Path to audit.json or audit-history directory")
    parser.add_argument("--port", "-p", type=int, default=3118, help="Server port (default: 3118)")
    parser.add_argument("--history", type=Path, default=None,
                        help="Path to audit-history directory (shorthand for history mode)")
    parser.add_argument(
        "--static", "-s", type=Path, default=None,
        help="Write standalone HTML to this path instead of starting a server",
    )
    parser.add_argument(
        "--relaunch", action="store_true",
        help="Kill any existing server on the port before starting a new one",
    )
    parser.add_argument(
        "--kill", action="store_true",
        help="Kill any existing server on the port and exit",
    )
    args = parser.parse_args()

    if args.kill:
        _kill_port(args.port)
        print(f"  Killed any server on port {args.port}")
        sys.exit(0)

    # Determine mode: history directory or single audit file
    target = args.history or args.audit_file
    if target is None:
        parser.error("either audit_file or --history is required")

    target = target.resolve()
    history_dir = None

    if target.is_dir():
        # History mode: serve all audits from the directory
        history_dir = target
        index, all_audits, all_responses = load_history(history_dir)

        # Use the most recent audit as the default view
        if index and index[0]["id"] in all_audits:
            latest_id = index[0]["id"]
            audit_data = all_audits[latest_id]
            existing_responses = all_responses.get(latest_id)
        else:
            audit_data = {"findings": [], "scope": "No audits", "specs_audited": []}
            existing_responses = None

        responses_path = history_dir / index[0]["id"] / "responses.json" if index else history_dir / "responses.json"
        html = generate_html(audit_data, existing_responses,
                             history_index=index,
                             all_audits=all_audits,
                             all_responses=all_responses)
        total = sum(len(a.get("findings", [])) for a in all_audits.values())
        label = f"{len(index)} audits, {total} total findings"
    else:
        # Single audit mode (backward compatible)
        audit_path = target
        audit_data = load_audit(audit_path)
        responses_path = audit_path.parent / "responses.json"

        existing_responses = None
        if responses_path.exists():
            try:
                existing_responses = json.loads(responses_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        html = generate_html(audit_data, existing_responses)
        label = f"{len(audit_data.get('findings', []))} findings"

    if args.static:
        args.static.parent.mkdir(parents=True, exist_ok=True)
        args.static.write_text(html)
        print(f"\n  Static review page written to: {args.static}\n")
        sys.exit(0)

    port = args.port

    # If a server is already running on this port, just open the browser and exit.
    # This prevents multiple server launches when the skill is invoked repeatedly.
    if _port_in_use(port):
        if args.relaunch:
            _kill_port(port)
        else:
            url = f"http://localhost:{port}"
            print(f"\n  Review server already running at {url}")
            print(f"  Opening browser... (use --relaunch to restart with new data)\n")
            webbrowser.open(url)
            sys.exit(0)

    handler = partial(ReviewHandler, html, responses_path, history_dir)
    try:
        server = HTTPServer(("127.0.0.1", port), handler)
    except OSError:
        server = HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]

    url = f"http://localhost:{port}"
    print(f"\n  Spec Audit Review")
    print(f"  {'─' * 35}")
    print(f"  URL:       {url}")
    print(f"  Target:    {target}")
    print(f"  {label}")
    print(f"\n  Press Ctrl+C to stop.\n")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
