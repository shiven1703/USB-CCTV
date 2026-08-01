"""Static checks for the Phase 1 package dependency boundary."""

from pathlib import Path


def test_domain_and_application_do_not_import_qt_or_outward_layers() -> None:
    source_root = Path(__file__).parents[2] / "src" / "usb_cctv_recorder"
    protected_packages = (source_root / "domain", source_root / "application")

    for package in protected_packages:
        for source_file in package.rglob("*.py"):
            source = source_file.read_text()
            assert "PySide6" not in source, source_file
            if package.name == "domain":
                assert "usb_cctv_recorder.infrastructure" not in source, source_file
                assert "usb_cctv_recorder.application" not in source, source_file
