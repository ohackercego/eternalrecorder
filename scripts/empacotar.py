"""Empacota o Eternal Recorder num ZIP portátil.

## O que faz

1. Confere que o runtime Python embarcado existe (`python-embed/`).
2. Instala as dependências em `python-embed/Lib/site-packages`.
3. Copia código, locales e config.
4. Gera `dist/Eternal Recorder 2.1.zip`.

## Por que ZIP e não instalador

O app é portátil por escolha: extrai e roda, sem registro, sem admin, sem
desinstalador. Um instalador só acrescentaria passos.

## Uso

    python scripts/empacotar.py
    python scripts/empacotar.py --sem-deps     # não reinstala dependências

Requer o Python embeddable em `python-embed/`. Se não existir, o script baixa
(Windows 64 bits, mesma versão do Python que você está rodando).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EMBED = RAIZ / "python-embed"
DIST = RAIZ / "dist"
VERSAO = "2.1.1"
NOME_ZIP = f"Eternal Recorder {VERSAO}.zip"

# o que entra no ZIP
INCLUIR = [
    "launcher.py",
    "config.ini",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "engine",
    "ui",
    "docs",
    "VERSION",
]
EXCLUIR_PADROES = ("__pycache__", "*.pyc", ".git", ".venv", "dist", "teste*")

PY_URL = ("https://www.python.org/ftp/python/{v}/"
          "python-{v}-embed-amd64.zip")


def log(msg: str) -> None:
    print(f"[empacotar] {msg}", flush=True)


def garantir_runtime() -> None:
    """Garante o Python embeddable e o site-packages."""
    exe = EMBED / "python.exe"
    if exe.exists():
        log(f"runtime presente: {exe}")
    else:
        v = f"{sys.version_info.major}.{sys.version_info.minor}." \
            f"{sys.version_info.micro}"
        url = PY_URL.format(v=v)
        log(f"baixando {url}")
        EMBED.mkdir(parents=True, exist_ok=True)
        tmp = EMBED.parent / "_python_embed.zip"
        urllib.request.urlretrieve(url, tmp)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(EMBED)
        tmp.unlink()
        # o ._pth restrito só enxerga Lib/site-packages; libera a pasta Lib
        for pth in EMBED.glob("python*._pth"):
            txt = pth.read_text(encoding="utf-8")
            if "Lib\\site-packages" not in txt:
                pth.write_text(txt + "\nLib\\site-packages\n",
                               encoding="utf-8")
        log("runtime instalado")

    (EMBED / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def instalar_dependencias() -> None:
    req = RAIZ / "requirements.txt"
    if not req.exists():
        log("requirements.txt ausente; pulando")
        return
    alvo = EMBED / "Lib" / "site-packages"
    log(f"instalando dependências em {alvo}")
    cmd = [sys.executable, "-m", "pip", "install",
           "--target", str(alvo),
           "--upgrade", "--no-compile",
           "-r", str(req)]
    r = subprocess.run(cmd, cwd=str(RAIZ))
    if r.returncode != 0:
        raise SystemExit("pip falhou; veja o erro acima")

    # cópia do runtime: o exe precisa achar as DLLs empacotadas
    log("dependências no lugar")


def copiar_codigo(destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for item in INCLUIR:
        origem = RAIZ / item
        if not origem.exists():
            log(f"AVISO: {item} não existe, pulando")
            continue
        alvo = destino / item
        if origem.is_dir():
            shutil.copytree(
                origem, alvo, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*EXCLUIR_PADROES))
        else:
            shutil.copy2(origem, alvo)
        log(f"copiado: {item}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-deps", action="store_true",
                    help="não reinstala as dependências")
    args = ap.parse_args()

    log(f"versão {VERSAO}")
    garantir_runtime()
    if not args.sem_deps:
        instalar_dependencias()

    tmp = RAIZ / "_empacotar"
    if tmp.exists():
        shutil.rmtree(tmp)
    copiar_codigo(tmp)

    # o runtime vai junto
    log("copiando runtime Python")
    shutil.copytree(EMBED, tmp / "python-embed", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # ── lançador ──
    # O Python embeddable NÃO traz pythonw.exe (só python.exe) — um .bat que
    # chamasse pythonw falharia em toda instalação. Aqui vai um VBScript que
    # roda python.exe com a janela escondida: mesmo efeito, sem console.
    (tmp / "Eternal Recorder.vbs").write_text(
        'Set sh = CreateObject("WScript.Shell")\r\n'
        'sh.CurrentDirectory = CreateObject("Scripting.FileSystemObject")'
        '.GetParentFolderName(WScript.ScriptFullName)\r\n'
        'sh.Run """python-embed\\python.exe"" launcher.py", 0, False\r\n',
        encoding="utf-8")

    # atalho .bat que mostra erro se algo faltar (para diagnóstico)
    (tmp / "Eternal Recorder.bat").write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        'start "" "python-embed\\python.exe" launcher.py\r\n',
        encoding="utf-8")
    log("lançadores criados (.vbs sem console, .bat com console)")

    # ZIP
    DIST.mkdir(parents=True, exist_ok=True)
    zip_path = DIST / NOME_ZIP
    if zip_path.exists():
        zip_path.unlink()
    log(f"zipando {zip_path.name}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in tmp.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(tmp))
    shutil.rmtree(tmp)

    tamanho = zip_path.stat().st_size / (1024 * 1024)
    log(f"PRONTO: {zip_path} ({tamanho:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
