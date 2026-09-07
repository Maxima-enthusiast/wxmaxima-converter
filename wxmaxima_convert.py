#!/usr/bin/env python3
"""Convert wxMaxima .wxm and .wxmx files in a Git repository.

The converter is deliberately dependency-free.  A wxmx file is a ZIP archive
containing XML and optional resources.  When converting it to wxm, the archive
is embedded in a marked base64 block after the readable cells.  Converting
that generated wxm back to wxmx restores the original bytes exactly, including
images and metadata that cannot be represented by the batch-file format.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ARCHIVE_BEGIN = "/* WXMAXIMA-CONVERTER: original wxmx (base64) BEGIN */"
ARCHIVE_END = "/* WXMAXIMA-CONVERTER: original wxmx (base64) END */"
CELL_BEGIN = "/* [wxMaxima: input   start ] */"
CELL_END = "/* [wxMaxima: input   end   ] */"
COMMENT_BEGIN = "/* [wxMaxima: comment start ] */"
COMMENT_END = "/* [wxMaxima: comment end   ] */"
VERSION_PATTERN = re.compile(r"Created\s+(?:using\s+)?wxMaxima\s+([0-9]+(?:\.[0-9]+)+)", re.IGNORECASE)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _cell_text(element: ET.Element) -> str:
    lines = [
        "".join(line.itertext())
        for line in element.iter()
        if _local_name(line.tag).lower() == "line"
    ]
    if lines:
        return "\n".join(lines).strip()
    return _text(element)


def _wxmaxima_version(xml_bytes: bytes) -> str:
    match = VERSION_PATTERN.search(xml_bytes.decode("utf-8", "replace"))
    if not match:
        raise ValueError("no se pudo identificar la versión de wxMaxima en content.xml")
    return match.group(1)


def _find_document_xml(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    preferred = ("content.xml", "document.xml", "worksheet.xml")
    for name in preferred:
        if name in names:
            return name
    for name in names:
        if name.lower().endswith(".xml"):
            return name
    raise ValueError("el archivo wxmx no contiene ningún XML de documento")


def _read_wxmx_document(source: Path) -> bytes:
    with zipfile.ZipFile(source) as archive:
        xml_name = _find_document_xml(archive)
        xml = archive.read(xml_name)
    root = ET.fromstring(xml)
    if _local_name(root.tag).lower() != "wxmaximadocument":
        raise ValueError(f"{source} no parece un documento wxMaxima")
    return xml


def _extract_cells(xml_bytes: bytes) -> list[tuple[str, str]]:
    root = ET.fromstring(xml_bytes)
    cells: list[tuple[str, str]] = []
    for element in root.iter():
        if _local_name(element.tag).lower() != "cell":
            continue
        cell_type = element.attrib.get("type", "").lower()
        input_element = next(
            (child for child in element.iter() if _local_name(child.tag).lower() in {"input", "text"}),
            None,
        )
        value = _cell_text(input_element) if input_element is not None else _cell_text(element)
        if not value:
            continue
        kind = "comment" if "text" in cell_type or "comment" in cell_type else "input"
        cells.append((kind, value))
    return cells


def _archive_block(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    lines = [ARCHIVE_BEGIN]
    lines.extend(encoded[index : index + 76] for index in range(0, len(encoded), 76))
    lines.append(ARCHIVE_END)
    return "\n".join(lines)


def _embedded_archive(text: str) -> bytes | None:
    match = re.search(
        re.escape(ARCHIVE_BEGIN) + r"\s*(.*?)\s*" + re.escape(ARCHIVE_END),
        text,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return base64.b64decode(re.sub(r"\s+", "", match.group(1)), validate=True)
    except ValueError as exc:
        raise ValueError("el bloque wxmx incrustado no es base64 válido") from exc


def wxmx_to_wxm(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    xml = _read_wxmx_document(source)
    version = _wxmaxima_version(xml)
    cells = _extract_cells(xml)

    chunks = [
        "/* [wxMaxima batch file version 1] [ DO NOT EDIT BY HAND! ]*/",
        f"/* [ Created with wxMaxima version {version} ] */",
        "",
    ]
    for kind, value in cells:
        if kind == "comment":
            chunks.extend((COMMENT_BEGIN, value, COMMENT_END, ""))
        else:
            chunks.extend((CELL_BEGIN, value, CELL_END, ""))
    chunks.extend(
        (
            "",
            _archive_block(data),
            "",
            '/* Old versions of Maxima abort on loading files that end in a comment. */',
            f'"Created with wxMaxima {version}"$',
            "",
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(chunks), encoding="utf-8", newline="\n")


def _xml_for_wxm(text: str) -> bytes:
    root = ET.Element("wxMaximaDocument", {"version": "1.5", "zoom": "100"})
    for match in re.finditer(
        re.escape(CELL_BEGIN) + r"\s*(.*?)\s*" + re.escape(CELL_END),
        text,
        re.DOTALL,
    ):
        cell = ET.SubElement(root, "cell", {"type": "code"})
        ET.SubElement(cell, "input").text = match.group(1).strip()
    if not list(root):
        cell = ET.SubElement(root, "cell", {"type": "code"})
        ET.SubElement(cell, "input").text = text
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def wxm_to_wxmx(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8")
    if "wxMaxima" not in text:
        raise ValueError(f"{source} no parece un archivo de texto wxMaxima")
    embedded = _embedded_archive(text)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if embedded is not None:
        destination.write_bytes(embedded)
        return
    xml = _xml_for_wxm(text)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", xml)


def _github_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {
        "github.com",
        "www.github.com",
    }


def _clone(url: str, destination: Path, commit: str | None) -> None:
    if not _github_url(url):
        raise ValueError("URL no válida: se requiere una URL de github.com")
    subprocess.run(
        ["git", "clone", url, str(destination)],
        check=True,
    )
    if commit:
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "--detach", commit],
            check=True,
        )


def _remove_clone(path: Path) -> None:
    def make_writable(
        function: object, failed_path: str, _: object
    ) -> None:
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    shutil.rmtree(path, onerror=make_writable)


def _selected_files(
    source: Path, paths: list[str], target: str, select_all: bool = False
) -> list[Path]:
    suffix = ".wxmx" if target == "wxmx" else ".wxm"
    opposite = ".wxm" if target == "wxmx" else ".wxmx"
    files: set[Path] = set()
    if select_all:
        paths = ["."]
    invalid_explicit: list[Path] = []
    for requested in paths:
        candidate = (source / requested).resolve()
        if candidate != source and source not in candidate.parents:
            raise ValueError(f"la ruta queda fuera del repositorio: {requested}")
        if not candidate.exists():
            raise FileNotFoundError(f"no existe la ruta indicada: {requested}")
        candidates = (
            candidate.rglob(f"*{opposite}")
            if candidate.is_dir()
            else [candidate]
        )
        for path in candidates:
            if path.is_file() and path.suffix.lower() == opposite:
                if target == "wxmx":
                    valid = "wxMaxima" in path.read_text(encoding="utf-8", errors="ignore")
                else:
                    try:
                        _read_wxmx_document(path)
                        valid = True
                    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
                        valid = False
                if valid:
                    files.add(path)
                elif not candidate.is_dir():
                    invalid_explicit.append(path)
    if invalid_explicit:
        names = ", ".join(str(path.relative_to(source)) for path in invalid_explicit)
        raise ValueError(f"los archivos indicados no son documentos wxMaxima: {names}")
    if not files:
        raise FileNotFoundError(
            f"no se encontraron documentos wxMaxima {opposite} en las rutas indicadas"
        )
    return sorted(files)


def convert_tree(source: Path, output: Path, target: str, paths: list[str]) -> int:
    files = _selected_files(source, paths, target)
    suffix = ".wxmx" if target == "wxmx" else ".wxm"
    for path in files:
        relative = path.relative_to(source).with_suffix(suffix)
        destination = output / relative
        if target == "wxmx":
            wxm_to_wxmx(path, destination)
        else:
            wxmx_to_wxm(path, destination)
    return len(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--repo", help="URL HTTPS de un repositorio de GitHub")
    input_group.add_argument("--source", type=Path, help="directorio local del repositorio")
    parser.add_argument("--to", choices=("wxm", "wxmx"), required=True, help="formato de salida")
    selection_group = parser.add_mutually_exclusive_group(required=True)
    selection_group.add_argument(
        "--path",
        action="append",
        help="ruta de archivo o directorio relativa al repositorio (se puede repetir)",
    )
    selection_group.add_argument(
        "--all",
        action="store_true",
        help="convertir todos los documentos wxMaxima válidos del commit",
    )
    parser.add_argument(
        "--commit",
        help="SHA (o referencia) que se debe convertir; por defecto se usa HEAD",
    )
    parser.add_argument("--output", type=Path, default=Path("converted-wxmaxima"))
    parser.add_argument("--keep-clone", action="store_true", help="conservar el clon temporal")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    temporary: Path | None = None
    try:
        if args.repo:
            temporary = Path(tempfile.mkdtemp(prefix="wxmaxima-repo-"))
            source = temporary / "repository"
            _clone(args.repo, source, args.commit)
        else:
            if args.commit:
                raise ValueError("--commit sólo está disponible junto con --repo")
            source = args.source.resolve()
            if not source.is_dir():
                raise NotADirectoryError(f"no es un directorio: {source}")
        paths = args.path or []
        count = convert_tree(
            source,
            args.output.resolve(),
            args.to,
            paths if not args.all else ["."],
        )
        print(f"Convertidos {count} archivos a .{args.to} en {args.output.resolve()}")
        return 0
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=os.sys.stderr)
        return 2
    finally:
        if temporary and not args.keep_clone:
            _remove_clone(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
