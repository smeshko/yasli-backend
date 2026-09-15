"""Local review tool for the flagged institution locations.

Run from the repo root::

    uv run python -m scripts.review_locations [--port 8765] [--no-browser]

A stdlib ``http.server`` bound to ``127.0.0.1`` serving one HTML page with a
map. Each decision — accept a candidate, place a pin, mark no pin — is
applied to the candidates file immediately and the CSV and provenance file
are regenerated from it through the loader's validating writer, so the tool
can never save a file the loader would reject: a rejected decision comes
back as ``422`` with the parser's message and nothing is written.

| Method | Path              | Does                                                  |
| ------ | ----------------- | ----------------------------------------------------- |
| GET    | ``/``             | the page                                              |
| GET    | ``/api/state``    | entries (pending first), counts, municipality outline |
| POST   | ``/api/decision`` | ``{key, status, candidate?, lat?, lon?, precision?}`` |
| POST   | ``/api/undo``     | revert the last decision of this session              |

On startup the lineage rule in ``scripts.location_review.state`` decides
whether the local candidates file or the committed files win, then the
derived files are regenerated — which also repairs a crash between the
candidates write and the derived writes, or between the CSV rename and the
provenance rename. With no candidates file at all the tool refuses to start
and points at the seed script.

Never imported by ``src/yasli``; never deployed. The page loads the map
library and tiles from the network; nothing in it calls a geocoder. The
server still treats the browser as untrusted on behalf of other sites: a
foreign ``Host`` or ``Origin``, or a POST body that is not
``application/json``, is refused before it is read (see
``ReviewHandler._refuse_foreign``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scripts.location_review import state
from yasli.ingest.institution_locations_loader import (
    DEFAULT_CSV,
    DEFAULT_PROVENANCE,
    LocationRowError,
)

log = logging.getLogger("scripts.review_locations")

INDEX_HTML = Path(__file__).resolve().parent / "location_review" / "index.html"
CANDIDATES_PATH = DEFAULT_CSV.with_name("institution_locations.candidates.json")
SEED_COMMAND = "uv run python -m scripts.seed_institution_locations"


class NoCandidatesFile(RuntimeError):
    """The review tool needs the seed script's output to exist."""


class ReviewState:
    """The entries under review, their files, and this session's undo stack."""

    def __init__(self, candidates_path: Path, csv_path: Path, provenance_path: Path) -> None:
        self.candidates_path = candidates_path
        self.csv_path = csv_path
        self.provenance_path = provenance_path
        doc = state.load_candidates(candidates_path)
        if doc is None:
            raise NoCandidatesFile(
                f"{candidates_path} does not exist. Run `{SEED_COMMAND}` first — it gathers "
                "candidates and rebuilds decisions from the committed CSV and provenance file."
            )
        committed_rows, committed_provenance, committed_hash_value, torn = state.load_committed(
            csv_path, provenance_path, doc
        )
        self.entries, rebuilt = state.reconcile(
            doc, committed_rows, committed_provenance, committed_hash_value, torn=torn
        )
        log.info(
            "%s: %d entries — %s",
            candidates_path,
            len(self.entries),
            "CSV and provenance file were torn by an interrupted save; regenerating both "
            "from the candidates file"
            if torn
            else "decisions rebuilt from the committed files"
            if rebuilt
            else "local decisions kept",
        )
        self.undo_stack: list[tuple[state.Key, dict[str, Any]]] = []
        self.lock = threading.Lock()
        self.persist()

    def persist(self) -> None:
        state.persist(
            self.entries.values(),
            candidates_path=self.candidates_path,
            csv_path=self.csv_path,
            provenance_path=self.provenance_path,
        )

    def snapshot(self) -> dict[str, Any]:
        return state.build_state(list(self.entries.values()))

    def counts(self) -> dict[str, int]:
        return state.counts_for(self.entries.values())

    def decide(self, key_dict: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        try:
            key: state.Key = tuple(str(key_dict[f]) for f in state.KEY_FIELDS)  # type: ignore[assignment]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"key must carry {', '.join(state.KEY_FIELDS)}") from exc
        if key not in self.entries:
            raise KeyError(key)
        previous = self.entries[key]
        new_entry = state.apply_decision(previous, request, today=date.today().isoformat())
        trial = {**self.entries, key: new_entry}
        state.validate(trial.values())  # LocationRowError → nothing written
        self.entries[key] = new_entry
        self.undo_stack.append((key, previous))
        self.persist()
        return new_entry

    def undo(self) -> dict[str, Any]:
        if not self.undo_stack:
            raise LookupError("nothing to undo")
        key, previous = self.undo_stack.pop()
        self.entries[key] = previous
        self.persist()
        return previous


class ReviewServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], review: ReviewState) -> None:
        self.review = review
        super().__init__(address, ReviewHandler)


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        log.debug(format, *args)

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refuse_foreign(self) -> bool:
        """Turn away requests that another site could have made the browser
        send, before any body is read. Returns True when a refusal went out.

        The server binds loopback, but a browser is a confused deputy: any
        page in another tab can POST here. Three doors are closed. A
        ``Host`` that is not this server (DNS rebinding) is refused on every
        method. On a POST, a body that is not ``application/json`` is
        refused — ``text/plain`` is a CORS "simple request" that skips the
        preflight, and this server answers no preflight, so requiring JSON
        makes every cross-origin fetch fail in the browser — and so is an
        ``Origin`` naming another site (or ``null``); clients that send no
        ``Origin`` at all (curl, the tests) are not browsers acting for a
        page and pass.
        """
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": f"unexpected Host {host!r}"})
            return True
        if self.command != "POST":
            return False
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"error": f"Content-Type must be application/json, not {content_type!r}"},
            )
            return True
        origin = self.headers.get("Origin")
        if origin is not None and origin.lower() not in {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": f"cross-site request from {origin!r}"})
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if self._refuse_foreign():
            return
        if self.path == "/":
            body = INDEX_HTML.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            with self.server.review.lock:
                self._send_json(HTTPStatus.OK, self.server.review.snapshot())
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no such path: {self.path}"})

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if self._refuse_foreign():
            return
        review = self.server.review
        try:
            body = self._read_body()
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"bad request body: {exc}"})
            return
        if self.path == "/api/decision":
            key = body.get("key")
            if not isinstance(key, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "key is required"})
                return
            with review.lock:
                try:
                    entry = review.decide(key, body)
                except KeyError:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no entry for key {key}"})
                    return
                except LocationRowError as exc:  # before ValueError: it is a subclass of it
                    self._send_json(
                        HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc), "line": exc.line_no}
                    )
                    return
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                except Exception as exc:  # the decision is in the candidates file already;
                    log.exception("persist failed")  # the derived files regenerate on next start
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": f"saved to the candidates file, but regenerating the CSV failed: {exc}"},
                    )
                    return
                self._send_json(
                    HTTPStatus.OK, {"entry": state.with_reasons(entry), "counts": review.counts()}
                )
        elif self.path == "/api/undo":
            with review.lock:
                try:
                    entry = review.undo()
                except LookupError as exc:
                    self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(
                    HTTPStatus.OK, {"entry": state.with_reasons(entry), "counts": review.counts()}
                )
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"no such path: {self.path}"})


def create_server(
    *,
    candidates_path: Path = CANDIDATES_PATH,
    csv_path: Path = DEFAULT_CSV,
    provenance_path: Path = DEFAULT_PROVENANCE,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ReviewServer:
    review = ReviewState(candidates_path, csv_path, provenance_path)
    return ReviewServer((host, port), review)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.review_locations",
        description="Review flagged institution locations on a local map.",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the page on start.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    try:
        server = create_server(
            candidates_path=args.candidates,
            csv_path=args.csv,
            provenance_path=args.provenance,
            port=args.port,
        )
    except (NoCandidatesFile, LocationRowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    counts = server.review.counts()
    print(
        f"review tool at {url} — to review: {counts['pending']}, "
        f"auto-accepted: {counts['auto']}, done: {counts['done']}",
        flush=True,
    )
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
