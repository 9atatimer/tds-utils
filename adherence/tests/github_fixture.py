"""Serve recorded GitHub REST responses to urllib, never the live API.

An opener built with `FixtureHandler` answers every https request from
the files under tests/fixtures/github_reviews: the URL's path plus `.json`
for its first page, `.page<N>.json` for page N, `.raw` for a request for
the raw media type, and `.status` holding an HTTP status for an error; a
`ref` query names `<path>@<ref>`. A path with no file is a 404. Every request is
kept on `requests`, so a test can read the headers the adapter sent.
"""

from __future__ import annotations

import io
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).parent / "fixtures" / "github_reviews"
REPOSITORY = "example-org/example"
TOKEN = "fixture-token"
RAW = "application/vnd.github.raw+json"
# The branch the judged landings are on.
BRANCH = "master"


class FixtureHandler(urllib.request.BaseHandler):
    # Ahead of urllib's own HTTPSHandler, so no request reaches a network.
    handler_order = 100

    def __init__(self, root: Path = FIXTURES) -> None:
        self.root = root
        self.requests: list[urllib.request.Request] = []

    def https_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(request)
        url = urlsplit(request.full_url)
        query = parse_qs(url.query)
        page = query.get("page", ["1"])[0]
        stem = self.root / url.path.lstrip("/")
        if "ref" in query:
            stem = stem.with_name(f"{stem.name}@{query['ref'][0]}")
        if request.get_header("Accept") == RAW:
            suffix = ".raw"
        else:
            suffix = ".json" if page == "1" else f".page{page}.json"
        body = stem.with_name(stem.name + suffix)
        status = stem.with_name(stem.name + ".status")
        headers = Message()
        headers["Content-Type"] = "application/json"
        if status.is_file():
            code, data = int(status.read_text().strip()), b'{"message": "error"}'
        elif body.is_file():
            code, data = 200, body.read_bytes()
        else:
            code, data = 404, b'{"message": "Not Found"}'
        response = urllib.response.addinfourl(
            io.BytesIO(data), headers, request.full_url, code
        )
        # urllib's own handlers set the reason phrase its error processor reads.
        response.msg = "OK" if code == 200 else "Error"
        return response


def fixture_opener() -> tuple[urllib.request.OpenerDirector, FixtureHandler]:
    handler = FixtureHandler()
    return urllib.request.build_opener(handler), handler
