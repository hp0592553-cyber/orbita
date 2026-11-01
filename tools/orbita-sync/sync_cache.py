#!/usr/bin/env python3
"""Audit and safely reconcile the Orbita Xbox 360 XC360 catalog/image cache.

This tool is deliberately offline: it never contacts Microsoft or the Xbox.
It only checks files already present in XC360/ and can rebuild IMGIDX.TXT.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROWS_MAGIC = "XCCROWS 2"
IDX_MAGIC = "XCCIMG 1"
TRAILER_SIZE = 32
MAX_IMAGE_SIZE = 768 * 1024
PRODUCT_RE = re.compile(r"^[A-Za-z0-9]{4,23}$")
IMAGE_DIRS = (("COVERS", "XCC1", 1), ("HERO", "XCH2", 2))


@dataclass
class Entry:
    product: str
    urls: int = 0
    disk: int = 0
    cover: str = ""
    hero: str = ""

    def line(self) -> str:
        return f"{self.product}\t{self.urls}\t{self.disk}\t{self.cover}\t{self.hero}"


def product_ok(value: str) -> bool:
    return bool(PRODUCT_RE.fullmatch(value or ""))


def fnv1a_product(product: str) -> str:
    """Same 32-bit FNV-1a over upper-case ASCII as xcc_file_name()."""
    h = 2166136261
    for byte in product.upper().encode("ascii"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h:08X}.JPG"


def read_text(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


def parse_rows(root: Path) -> tuple[list[str], list[str]]:
    path = root / "ROWS.TXT"
    errors: list[str] = []
    products: list[str] = []
    if not path.is_file():
        return products, ["ROWS.TXT ausente; não há lista confiável para sincronizar."]
    try:
        lines = read_text(path)
    except (OSError, UnicodeError) as exc:
        return products, [f"não consegui ler ROWS.TXT: {exc}"]
    if not lines or lines[0].strip() != ROWS_MAGIC:
        return products, [f"cabeçalho inválido em ROWS.TXT (esperado {ROWS_MAGIC})."]
    row = -1
    for number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        if line.startswith("#ROW "):
            try:
                row = int(line[5:])
            except ValueError:
                row = -1
            if row not in range(4):
                errors.append(f"ROWS.TXT:{number}: marcador de fileira inválido.")
            continue
        fields = line.split("\t", 3)
        if row not in range(4) or len(fields) != 4:
            errors.append(f"ROWS.TXT:{number}: registro fora de fileira ou com colunas incompletas.")
            continue
        title_id, product, flags, _name = fields
        if not title_id or not product_ok(product):
            errors.append(f"ROWS.TXT:{number}: titleId/bigId inválido.")
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{1,8}", flags):
            errors.append(f"ROWS.TXT:{number}: flags não são hexadecimais.")
            continue
        products.append(product.upper())
    return list(dict.fromkeys(products)), errors


def parse_index(root: Path) -> tuple[list[Entry], list[str], bool]:
    path = root / "IMGIDX.TXT"
    if not path.exists():
        return [], [], False
    errors: list[str] = []
    entries: list[Entry] = []
    try:
        lines = read_text(path)
    except (OSError, UnicodeError) as exc:
        return [], [f"não consegui ler IMGIDX.TXT: {exc}"], True
    if not lines or lines[0].strip() != IDX_MAGIC:
        return [], [f"cabeçalho inválido em IMGIDX.TXT (esperado {IDX_MAGIC}); arquivo preservado."], True
    seen: set[str] = set()
    for number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            errors.append(f"IMGIDX.TXT:{number}: registro com quantidade de colunas inválida.")
            continue
        product, urls_s, disk_s, cover, hero = fields
        product = product.upper()
        if not product_ok(product):
            errors.append(f"IMGIDX.TXT:{number}: bigId inválido.")
            continue
        if product in seen:
            errors.append(f"IMGIDX.TXT:{number}: bigId duplicado ({product}).")
            continue
        if urls_s not in ("0", "1") or disk_s not in ("0", "1", "2", "3"):
            errors.append(f"IMGIDX.TXT:{number}: flags urls/disk inválidas.")
            continue
        for label, value in (("capa", cover), ("hero", hero)):
            if value and (not value.startswith("/") or "?" in value or ".." in value or
                          any(ord(ch) < 32 for ch in value) or len(value) >= 160):
                errors.append(f"IMGIDX.TXT:{number}: caminho de {label} inválido.")
        if any((cover, hero)) and not int(urls_s):
            errors.append(f"IMGIDX.TXT:{number}: caminho de imagem existe com urls=0.")
        seen.add(product)
        entries.append(Entry(product, int(urls_s), int(disk_s), cover, hero))
    return entries, errors, True


def inspect_image(path: Path, product: str, magic: str) -> tuple[bool, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return False, f"não foi possível ler: {exc}"
    if len(data) <= TRAILER_SIZE + 4 or len(data) > MAX_IMAGE_SIZE:
        return False, "tamanho fora do limite"
    jpg, trailer = data[:-TRAILER_SIZE], data[-TRAILER_SIZE:]
    if jpg[:2] != b"\xff\xd8" or jpg[-2:] != b"\xff\xd9":
        return False, "JPEG sem SOI/EOI completo (possível download truncado)"
    if trailer[:4] != magic.encode("ascii"):
        return False, "trailer de capa/hero incorreto"
    expected = product.encode("ascii")
    if trailer[4:4 + len(expected)] != expected or any(trailer[4 + len(expected):]):
        return False, "bigId no trailer não corresponde ao arquivo"
    return True, ""


def discover_images(root: Path) -> tuple[dict[str, int], list[str], int]:
    valid: dict[str, int] = {}
    warnings: list[str] = []
    seen_files = 0
    for dirname, magic, bit in IMAGE_DIRS:
        folder = root / dirname
        if not folder.exists():
            continue
        if not folder.is_dir():
            warnings.append(f"{dirname}: existe, mas não é uma pasta.")
            continue
        for path in sorted(folder.glob("*.JPG")) + sorted(folder.glob("*.jpg")):
            seen_files += 1
            try:
                data = path.read_bytes()
            except OSError as exc:
                warnings.append(f"{path.relative_to(root)}: leitura falhou: {exc}")
                continue
            if len(data) < TRAILER_SIZE:
                warnings.append(f"{path.relative_to(root)}: arquivo sem trailer.")
                continue
            trailer = data[-TRAILER_SIZE:]
            if trailer[:4] != magic.encode("ascii"):
                warnings.append(f"{path.relative_to(root)}: assinatura {magic} ausente.")
                continue
            raw = trailer[4:]
            product_bytes = raw.split(b"\0", 1)[0]
            try:
                product = product_bytes.decode("ascii").upper()
            except UnicodeDecodeError:
                warnings.append(f"{path.relative_to(root)}: bigId não é ASCII.")
                continue
            if not product_ok(product):
                warnings.append(f"{path.relative_to(root)}: bigId do trailer inválido.")
                continue
            expected_name = fnv1a_product(product)
            if path.name.upper() != expected_name:
                warnings.append(f"{path.relative_to(root)}: nome deveria ser {expected_name}.")
                continue
            ok, why = inspect_image(path, product, magic)
            if not ok:
                warnings.append(f"{path.relative_to(root)}: {why}.")
                continue
            valid[product] = valid.get(product, 0) | bit
    return valid, warnings, seen_files


def render_index(entries: list[Entry]) -> bytes:
    rows = [IDX_MAGIC]
    rows.extend(entry.line() for entry in entries)
    return ("\n".join(rows) + "\n").encode("utf-8")


def atomic_write_index(root: Path, content: bytes, had_index: bool) -> None:
    target = root / "IMGIDX.TXT"
    backup = root / "IMGIDX.BAK"
    if had_index and target.exists() and not backup.exists():
        # Keep one original 8.3 backup; never overwrite a previous backup.
        backup.write_bytes(target.read_bytes())
    temp = root / "IMGIDX.NEW"
    with temp.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)


def audit(root: Path, repair: bool = False) -> int:
    root = root.expanduser().resolve()
    if not root.is_dir():
        print(f"ERRO: pasta XC360 não encontrada: {root}", file=sys.stderr)
        return 2

    products, row_errors = parse_rows(root)
    entries, idx_errors, had_index = parse_index(root)
    fatal_index = any("cabeçalho inválido" in item or "não consegui ler IMGIDX" in item
                      for item in idx_errors)
    fatal_rows = any("ausente" in item or "cabeçalho inválido" in item or
                     "não consegui ler ROWS" in item for item in row_errors)
    valid_files, file_warnings, total_files = discover_images(root)

    by_product = {entry.product: entry for entry in entries}
    before = len(entries)
    for product in products:
        by_product.setdefault(product, Entry(product))
    for product, mask in valid_files.items():
        by_product.setdefault(product, Entry(product))
    entries = list(by_product.values())

    stale_flags = 0
    good_images = 0
    missing_flags = 0
    for entry in entries:
        actual = valid_files.get(entry.product, 0)
        good_images += bool(actual & 1) + bool(actual & 2)
        if entry.disk != actual:
            stale_flags += 1
            if entry.disk & ~actual:
                missing_flags += 1
            entry.disk = actual

    missing_products = sum(1 for product in products if product not in
                           {item.product for item in parse_index(root)[0]})
    orphan_files = max(0, len(valid_files) - len(parse_index(root)[0]))
    issues = len(row_errors) + len(idx_errors) + len(file_warnings) + stale_flags + missing_products

    print(f"XC360: {root}")
    print(f"ROWS.TXT: {len(products)} bigIds únicos; {len(row_errors)} problema(s).")
    print(f"IMGIDX.TXT: {before} entrada(s) antes; {len(entries)} após reconciliar.")
    print(f"Imagens: {good_images} válidas; {total_files} arquivo(s) visto(s).")
    print(f"Índice: {stale_flags} flag(s) disk divergente(s), {missing_products} produto(s) sem entrada, "
          f"{orphan_files} produto(s) recuperado(s) por trailer.")
    for message in row_errors + idx_errors + file_warnings:
        print(f"AVISO: {message}")

    if repair:
        if fatal_rows or fatal_index:
            print("REPARO CANCELADO: cabeçalho/lista principal inválida; nenhum arquivo foi alterado.")
            return 2
        if row_errors or idx_errors:
            print("REPARO CANCELADO: registros inválidos; corrija/recupere os arquivos antes de gravar.")
            return 2
        atomic_write_index(root, render_index(entries), had_index)
        print("OK: IMGIDX.TXT reconstruído; backup IMGIDX.BAK preservado quando já existia índice.")
        print("Nenhuma capa, hero, ROWS.TXT ou outro arquivo foi apagado/alterado.")
        return 0

    return 1 if issues else 0


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="orbita-sync-test-") as temp:
        root = Path(temp)
        (root / "COVERS").mkdir()
        (root / "HERO").mkdir()
        product = "9NBLGGH4R315"
        (root / "ROWS.TXT").write_text(
            f"{ROWS_MAGIC}\n#ROW 3\nT123\t{product}\t1\tJogo teste\n",
            encoding="utf-8")
        jpg = b"\xff\xd8" + b"orbita-test-image" + b"\xff\xd9"
        trailer = b"XCC1" + product.encode("ascii") + bytes(28 - len(product))
        (root / "COVERS" / fnv1a_product(product)).write_bytes(jpg + trailer)
        # Disk bit deliberately incorrect and one game missing from IMGIDX.
        (root / "IMGIDX.TXT").write_text(
            f"{IDX_MAGIC}\n{product}\t1\t0\t/image/cover\t\n",
            encoding="utf-8")
        if audit(root, repair=False) != 1:
            print("SELF-TEST FAIL: o índice divergente não foi detectado.", file=sys.stderr)
            return 1
        if audit(root, repair=True) != 0:
            print("SELF-TEST FAIL: a reconstrução falhou.", file=sys.stderr)
            return 1
        lines = read_text(root / "IMGIDX.TXT")
        if lines[0] != IDX_MAGIC or f"{product}\t1\t1\t/image/cover\t" not in lines:
            print("SELF-TEST FAIL: flags reconstruídas incorretamente.", file=sys.stderr)
            return 1
        if not (root / "IMGIDX.BAK").is_file():
            print("SELF-TEST FAIL: backup do índice não foi criado.", file=sys.stderr)
            return 1
    print("SELF-TEST PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Confere e sincroniza o cache local XC360 sem apagar artes.")
    parser.add_argument("xc360", nargs="?", type=Path,
                        help="pasta XC360 copiada do pendrive")
    parser.add_argument("--repair-index", action="store_true",
                        help="reconstrói IMGIDX.TXT e cria IMGIDX.BAK; não baixa nem apaga imagens")
    parser.add_argument("--self-test", action="store_true",
                        help="executa um teste local sem pendrive")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.xc360 is None:
        parser.error("informe a pasta XC360 ou use --self-test")
    return audit(args.xc360, repair=args.repair_index)


if __name__ == "__main__":
    raise SystemExit(main())
