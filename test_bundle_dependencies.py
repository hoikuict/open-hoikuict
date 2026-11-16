from pathlib import Path

import pytest

from scripts.build_beta_bundle import validate_dependencies


def install_metadata(root: Path, name: str, version: str):
    folder = root / f"{name}-{version}.dist-info"
    folder.mkdir(parents=True)
    (folder / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8")


@pytest.mark.parametrize("name,old,new", [
    ("Pillow", "12.3.0", "13.0.0"),
    ("starlette", "0.52.1", "1.3.1"),
    ("python-multipart", "0.0.20", "0.0.32"),
    ("python-dotenv", "1.1.1", "1.2.4"),
])
def test_bundle_rejects_stale_dependencies(tmp_path, name, old, new):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"{name}=={new}\n", encoding="utf-8")
    install_metadata(tmp_path / "old", name, old)
    with pytest.raises(ValueError, match="Bundle dependency mismatch"):
        validate_dependencies(requirements, tmp_path / "old")
    install_metadata(tmp_path / "new", name, new)
    validate_dependencies(requirements, tmp_path / "new")


def test_bundle_checks_missing_packages_extras_and_normalized_names(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("# runtime\nuvicorn[standard]==0.41.0\npython-dotenv>=1.2.2\n", encoding="utf-8")
    install_metadata(tmp_path, "uvicorn", "0.41.0")
    with pytest.raises(ValueError, match="python-dotenv.*missing"):
        validate_dependencies(requirements, tmp_path)
    install_metadata(tmp_path, "python_dotenv", "1.2.4")
    validate_dependencies(requirements, tmp_path)
