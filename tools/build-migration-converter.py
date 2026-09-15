"""Build a self-contained offline converter from the same tested app source."""
import argparse
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_transfer_service import dataset_options  # noqa: E402
from template_utils import create_templates  # noqa: E402


def build(destination: Path):
    schemas = [{"id": item.id, "label": item.label, "headers": list(item.all_headers)} for item in dataset_options()]
    templates = create_templates(str(ROOT / "templates"))
    markup = templates.env.get_template("data_transfers/converter.html").render(
        schemas=schemas, offline=True, request=SimpleNamespace(state=SimpleNamespace(csrf_token="")),
    )
    assets = ROOT / "assets/migration"
    code = "\n".join(re.sub(r"^export ", "", (assets / name).read_text(encoding="utf-8"), flags=re.M) for name in ("core.js", "files.js"))
    app = re.sub(r"^import .+?;\n", "", (assets / "app.js").read_text(encoding="utf-8"), flags=re.M)
    code += "\n" + app
    assert "</script" not in code.lower()
    markup, style_count = re.subn(r'<link rel="stylesheet" href="/data-transfers/converter/assets/style.css">', lambda _: "<style>" + (assets / "style.css").read_text(encoding="utf-8") + "</style>", markup)
    markup, script_count = re.subn(r'<script type="module" src="/data-transfers/converter/assets/app.js"></script>', lambda _: '<script type="module">\n' + code + "\n</script>", markup)
    assert style_count == script_count == 1
    policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'"
    markup = markup.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + policy + '">')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(markup, encoding="utf-8", newline="\n")
    print(f"Offline converter: {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
