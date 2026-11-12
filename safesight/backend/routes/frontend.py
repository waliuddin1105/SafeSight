"""Built dashboard asset delivery."""

from __future__ import annotations


from flask import abort, send_file

from safesight.config import ROOT, within


from flask import Blueprint

bp = Blueprint("frontend", __name__)


@bp.get("/")
@bp.get("/<path:asset>")
def frontend(asset="index.html"):
    directory = ROOT / "frontend/dist"
    path = within(directory, asset)
    if path.is_file():
        return send_file(path)
    if (directory / "index.html").is_file() and not asset.startswith("api/"):
        return send_file(directory / "index.html")
    abort(404)
