import hashlib
import io
import json
import configparser
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from app.subtitle_cleanup import (
    ReleaseAsset,
    ReleaseUpdate,
    SubtitleCleanupTool,
    UpdateError,
    is_newer_version,
)
from app.subtitle_gui import SubtitleSpellcheckGUI


class FakeResponse:
    def __init__(self, data: bytes, url: str):
        self._stream = io.BytesIO(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url


def zip_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("SubtitleUniverseSpellcheck-1.1.0/README.md", "release")
    return output.getvalue()


def release_payload(asset_name: str, payload: bytes) -> bytes:
    checksum_name = asset_name + ".sha256"
    digest = hashlib.sha256(payload).hexdigest()
    return json.dumps(
        {
            "tag_name": "v1.1.0",
            "name": "Subtitle Universe Spellcheck 1.1.0",
            "html_url": "https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/tag/v1.1.0",
            "body": "GUI release",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": asset_name,
                    "browser_download_url": f"https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/{asset_name}",
                    "size": len(payload),
                    "digest": f"sha256:{digest}",
                },
                {
                    "name": checksum_name,
                    "browser_download_url": f"https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/{checksum_name}",
                    "size": 128,
                    "digest": None,
                },
            ],
        }
    ).encode("utf-8")


class UpdateTests(unittest.TestCase):
    def test_update_consent_is_persisted_separately_from_boolean_value(self):
        tool = SubtitleCleanupTool()
        tool.update_check_preference_confirmed = False
        tool.options["check_for_updates_at_startup"] = False
        with tempfile.TemporaryDirectory() as temp_dir:
            tool.options_path = Path(temp_dir) / "options.ini"
            tool.set_option_value("check_for_updates_at_startup", False)
            parser = configparser.ConfigParser()
            parser.read(tool.options_path, encoding="utf-8")

        self.assertFalse(parser.getboolean("options", "check_for_updates_at_startup"))
        self.assertTrue(parser.getboolean("options", "update_check_preference_confirmed"))

    def test_cli_first_run_decline_is_saved_before_any_network_check(self):
        tool = SubtitleCleanupTool()
        tool.update_check_preference_confirmed = False
        tool.options["check_for_updates_at_startup"] = False
        tool.check_for_update = Mock()
        def save_choice(key, value):
            tool.options[key] = value
            tool.update_check_preference_confirmed = True

        tool.set_option_value = Mock(side_effect=save_choice)

        with (
            patch("builtins.input", return_value="n"),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            tool.check_for_updates_cli()

        tool.set_option_value.assert_called_once_with("check_for_updates_at_startup", False)
        tool.check_for_update.assert_not_called()
        self.assertTrue(tool.update_check_preference_confirmed)

    def test_gui_first_run_consent_is_saved_before_scheduling_check(self):
        gui = SubtitleSpellcheckGUI.__new__(SubtitleSpellcheckGUI)
        gui.tool = Mock()
        gui.tool.update_check_preference_confirmed = False
        gui.tool.options = {"check_for_updates_at_startup": False}
        gui.tool.set_option_value.side_effect = lambda key, value: gui.tool.options.__setitem__(
            key, value
        )
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = True
        gui._offer_gui_recovery = Mock()
        gui._begin_update_check = Mock()
        gui.root = Mock()

        gui._complete_startup()

        gui.tool.set_option_value.assert_called_once_with(
            "check_for_updates_at_startup", True
        )
        gui.root.after.assert_called_once_with(750, gui._begin_update_check)

    def test_version_comparison_handles_stable_and_development_versions(self):
        self.assertTrue(is_newer_version("1.1.0", "1.0.0-rc4-dev64"))
        self.assertTrue(is_newer_version("1.0.0", "1.0.0-rc4-dev64"))
        self.assertFalse(is_newer_version("1.0.0-rc3", "1.0.0-rc4-dev64"))
        self.assertFalse(is_newer_version("1.1.0", "1.1.0"))

    def test_update_check_selects_source_asset_for_source_launch(self):
        payload = zip_bytes()
        asset_name = "SubtitleUniverseSpellcheck-1.1.0-source.zip"
        response = FakeResponse(
            release_payload(asset_name, payload),
            "https://api.github.com/repos/gearheart89/subtitle-universe-spellcheck-public/releases/latest",
        )
        tool = SubtitleCleanupTool()

        update = tool.check_for_update(
            current_version="1.0.0",
            frozen=False,
            platform_name="win32",
            opener=Mock(return_value=response),
        )

        self.assertEqual(update.version, "1.1.0")
        self.assertEqual(update.asset.name, asset_name)
        self.assertEqual(update.checksum_asset.name, asset_name + ".sha256")

    def test_update_check_selects_windows_asset_only_for_frozen_windows(self):
        payload = zip_bytes()
        asset_name = "SubtitleUniverseSpellcheck-1.1.0-windows-x64.zip"
        response = FakeResponse(
            release_payload(asset_name, payload),
            "https://api.github.com/repos/gearheart89/subtitle-universe-spellcheck-public/releases/latest",
        )
        tool = SubtitleCleanupTool()

        update = tool.check_for_update(
            current_version="1.0.0",
            frozen=True,
            platform_name="win32",
            machine="AMD64",
            opener=Mock(return_value=response),
        )

        self.assertEqual(update.asset.name, asset_name)

    def test_update_check_returns_none_when_release_is_not_newer(self):
        payload = zip_bytes()
        response = FakeResponse(
            release_payload("SubtitleUniverseSpellcheck-1.1.0-source.zip", payload),
            "https://api.github.com/repos/gearheart89/subtitle-universe-spellcheck-public/releases/latest",
        )
        tool = SubtitleCleanupTool()

        self.assertIsNone(
            tool.check_for_update(
                current_version="1.1.0",
                frozen=False,
                opener=Mock(return_value=response),
            )
        )

    def test_verified_download_publishes_zip_and_checksum_atomically(self):
        payload = zip_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        asset = ReleaseAsset(
            "SubtitleUniverseSpellcheck-1.1.0-source.zip",
            "https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/source.zip",
            len(payload),
            f"sha256:{digest}",
        )
        checksum = ReleaseAsset(
            asset.name + ".sha256",
            "https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/source.zip.sha256",
            100,
            None,
        )
        release = ReleaseUpdate(
            "1.1.0", "v1.1.0", "Release", "https://github.com/release", "", asset, checksum
        )
        responses = {
            asset.url: FakeResponse(payload, asset.url),
            checksum.url: FakeResponse(
                f"{digest}  {asset.name}\n".encode("ascii"), checksum.url
            ),
        }
        tool = SubtitleCleanupTool()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / asset.name
            archive_path, checksum_path = tool.download_update(
                release,
                destination,
                opener=lambda request, timeout: responses[request.full_url],
            )

            self.assertEqual(archive_path.read_bytes(), payload)
            self.assertEqual(
                checksum_path.read_text(encoding="ascii"),
                f"{digest}  {archive_path.name}\n",
            )
            self.assertFalse(destination.with_suffix(".zip.part").exists())

    def test_checksum_mismatch_leaves_no_download(self):
        payload = zip_bytes()
        asset = ReleaseAsset(
            "SubtitleUniverseSpellcheck-1.1.0-source.zip",
            "https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/source.zip",
            len(payload),
            None,
        )
        checksum = ReleaseAsset(
            asset.name + ".sha256",
            "https://github.com/gearheart89/subtitle-universe-spellcheck-public/releases/download/v1.1.0/source.zip.sha256",
            100,
            None,
        )
        release = ReleaseUpdate(
            "1.1.0", "v1.1.0", "Release", "https://github.com/release", "", asset, checksum
        )
        responses = {
            asset.url: FakeResponse(payload, asset.url),
            checksum.url: FakeResponse(("0" * 64 + "  source.zip\n").encode("ascii"), checksum.url),
        }
        tool = SubtitleCleanupTool()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / asset.name
            with self.assertRaisesRegex(UpdateError, "checksum"):
                tool.download_update(
                    release,
                    destination,
                    opener=lambda request, timeout: responses[request.full_url],
                )

            self.assertFalse(destination.exists())
            self.assertFalse(Path(str(destination) + ".sha256").exists())
            self.assertFalse(Path(str(destination) + ".part").exists())

    def test_cli_update_offer_downloads_platform_selected_zip(self):
        tool = SubtitleCleanupTool()
        tool.update_check_preference_confirmed = True
        tool.options["check_for_updates_at_startup"] = True
        update = Mock()
        update.version = "1.1.0"
        update.name = "Subtitle Universe Spellcheck 1.1.0"
        update.page_url = "https://github.com/release"
        update.asset.name = "SubtitleUniverseSpellcheck-1.1.0-source.zip"
        tool.check_for_update = Mock(return_value=update)
        tool.download_update = Mock()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / update.asset.name
            tool.download_update.return_value = (
                destination,
                Path(str(destination) + ".sha256"),
            )
            with (
                patch("builtins.input", side_effect=["y", str(destination)]),
                patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                tool.check_for_updates_cli()

        tool.download_update.assert_called_once_with(update, destination)
        self.assertIn("Version 1.1.0 is available", output.getvalue())
        self.assertIn("Downloaded and verified", output.getvalue())

    def test_gui_update_offer_uses_selected_release_asset(self):
        gui = SubtitleSpellcheckGUI.__new__(SubtitleSpellcheckGUI)
        gui.messagebox = Mock()
        gui.messagebox.askyesno.return_value = True
        gui.filedialog = Mock()
        gui.tool = Mock()
        gui.tool.script_dir = Path("C:/portable")
        gui._start_update_download = Mock()
        update = Mock()
        update.version = "1.1.0"
        update.name = "Subtitle Universe Spellcheck 1.1.0"
        update.page_url = "https://github.com/release"
        update.asset.name = "SubtitleUniverseSpellcheck-1.1.0-source.zip"
        gui.filedialog.asksaveasfilename.return_value = "C:/Downloads/" + update.asset.name

        gui._offer_update_download(update)

        self.assertEqual(
            gui.filedialog.asksaveasfilename.call_args.kwargs["initialfile"],
            update.asset.name,
        )
        gui._start_update_download.assert_called_once_with(
            update, Path("C:/Downloads") / update.asset.name
        )

    def test_windows_builder_keeps_tls_support_for_update_downloads(self):
        builder = (Path(__file__).resolve().parents[1] / "tools" / "build_windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("--exclude-module ssl", builder)
        self.assertNotIn("--exclude-module _ssl", builder)
        self.assertNotIn("--exclude-module _hashlib", builder)


if __name__ == "__main__":
    unittest.main()
