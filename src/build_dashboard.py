"""
Build the static dashboard: inject docs/data.json into dashboard/template.html.

Outputs
  docs/index.html          full HTML page, served by GitHub Pages (the live demo)
  dashboard/embed.html     same page without the <html>/<head> wrapper (for hosts that add their own)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = "Hamad Ur Rehman"   # <- change to your name as it appears on your CV


def main() -> None:
    data = json.loads((ROOT / "docs" / "data.json").read_text())
    body = (ROOT / "dashboard" / "template.html").read_text()
    body = body.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    body = body.replace("__AUTHOR__", AUTHOR)
    (ROOT / "dashboard" / "embed.html").write_text(body)

    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            "<style>[hidden]{display:none!important} body{margin:0} img{max-width:100%}</style>\n"
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    (ROOT / "docs" / "index.html").write_text(page)
    (ROOT / "docs" / ".nojekyll").write_text("")
    print(f"Built docs/index.html ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
