import zipfile
import tempfile
import unittest
from pathlib import Path

from wxmaxima_convert import convert_tree, wxm_to_wxmx, wxmx_to_wxm


def make_wxmx(path: Path) -> bytes:
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
<wxMaximaDocument version="1.5">
  <cell type="code"><input>2 + 2;</input></cell>
  <cell type="text"><text>Example note</text></cell>
</wxMaximaDocument>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", content)
        archive.writestr("image.png", b"binary resource")
    return path.read_bytes()


class ConverterTests(unittest.TestCase):
    def test_wxmx_to_wxm_keeps_readable_cells_and_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            original = tmp_path / "sample.wxmx"
            original_bytes = make_wxmx(original)
            converted = tmp_path / "sample.wxm"

            wxmx_to_wxm(original, converted)

            text = converted.read_text(encoding="utf-8")
            self.assertIn("2 + 2;", text)
            self.assertIn("Example note", text)
            self.assertIn("WXMAXIMA-CONVERTER: original wxmx", text)
            restored = tmp_path / "restored.wxmx"
            wxm_to_wxmx(converted, restored)
            self.assertEqual(restored.read_bytes(), original_bytes)

    def test_wxm_to_wxmx_creates_document(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "sample.wxm"
            source.write_text(
                "/* [wxMaxima: input   start ] */\n"
                "integrate(x^2, x);\n"
                "/* [wxMaxima: input   end   ] */\n",
                encoding="utf-8",
            )
            destination = tmp_path / "sample.wxmx"

            wxm_to_wxmx(source, destination)

            with zipfile.ZipFile(destination) as archive:
                self.assertIn("content.xml", archive.namelist())
                self.assertIn(b"integrate(x^2, x);", archive.read("content.xml"))

    def test_convert_tree_only_processes_explicit_path(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            selected = tmp_path / "selected.wxm"
            ignored = tmp_path / "ignored.wxm"
            selected.write_text(
                "/* [wxMaxima batch file version 1] */\n"
                "/* [wxMaxima: input start ] */\n"
                "x;\n",
                encoding="utf-8",
            )
            ignored.write_text("not a wxMaxima file", encoding="utf-8")

            output = tmp_path / "out"
            self.assertEqual(convert_tree(tmp_path, output, "wxmx", ["selected.wxm"]), 1)
            self.assertTrue((output / "selected.wxmx").exists())
            self.assertFalse((output / "ignored.wxmx").exists())


if __name__ == "__main__":
    unittest.main()
