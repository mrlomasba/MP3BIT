"""Arregla las canciones que Safari (iPhone) no puede adelantar en streaming.

Uso:  python scripts/fix_audio.py      (lo ejecuta el robot de GitHub antes del catálogo)

Muchas páginas que "bajan MP3 de YouTube" entregan en realidad un MP4 fragmentado
(DASH) con extensión .mp3. Suena, pero Safari no puede saltar dentro de él. Este
script lo reorganiza como un .m4a normal con el índice al principio:
  - MP4/M4A fragmentado, con el índice al final o con extensión equivocada
      → .m4a sin recomprimir (misma calidad, solo se reacomoda el archivo)
  - WebM disfrazado (.mp3 que es WebM/Opus) → .m4a (AAC 192 kbps)
Los MP3 de verdad no se tocan. El original se borra solo si el nuevo quedó bien.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC = ROOT / "music"
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".mp4", ".wav", ".flac", ".ogg", ".opus", ".webm"}


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def top_boxes(path: Path) -> tuple[str, list[str]]:
    """Marca (brand) y lista de cajas de primer nivel de un MP4; ('', []) si no es MP4."""
    brand, names = "", []
    with path.open("rb") as f:
        size_total = path.stat().st_size
        pos = 0
        while pos + 8 <= size_total and len(names) < 100000:
            f.seek(pos)
            head = f.read(16)
            if len(head) < 8:
                break
            size, typ = struct.unpack(">I4s", head[:8])
            if size == 1 and len(head) >= 16:
                size = struct.unpack(">Q", head[8:16])[0]
            elif size == 0:
                size = size_total - pos
            if size < 8:
                break
            name = typ.decode("latin1")
            if pos == 0:
                if name != "ftyp":
                    return "", []
                brand = head[8:12].decode("latin1") if size >= 12 and size_total >= 12 else ""
            names.append(name)
            pos += size
    return brand, names


def kind(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(12)
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return "other"


def mp4_problem(path: Path) -> str | None:
    brand, names = top_boxes(path)
    if not names:
        return None
    if brand.strip() == "dash" or "moof" in names:
        return "MP4 fragmentado"
    if "moov" in names and "mdat" in names and names.index("moov") > names.index("mdat"):
        return "índice al final"
    if path.suffix.lower() != ".m4a":
        return f"es M4A con extensión {path.suffix}"
    return None


def target_for(path: Path) -> Path:
    # Mismo nombre con .m4a. Si ya existe (la misma canción subida otra vez), se reemplaza.
    return path.with_suffix(".m4a")


def convert(ffmpeg: str, src: Path, dst: Path, reencode: bool) -> bool:
    tmp = dst.with_name(dst.stem + ".tmp.m4a")
    codec = ["-c:a", "aac", "-b:a", "192k"] if reencode else ["-c:a", "copy"]
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-map_metadata", "0",
           *codec, "-movflags", "+faststart", "-f", "mp4", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1024
    if ok:
        # Comprobación: el resultado ya no está fragmentado y tiene el índice al principio
        brand, names = top_boxes(tmp)
        ok = "moof" not in names and "moov" in names and "mdat" in names \
            and names.index("moov") < names.index("mdat")
    if not ok:
        print(f"  ERROR con {src.name}: {r.stderr.strip()[:300]}")
        tmp.unlink(missing_ok=True)
        return False
    if src == dst:
        src.unlink()
    tmp.replace(dst)
    if src != dst:
        src.unlink()
    return True


def main() -> int:
    if not MUSIC.exists():
        return 0
    todo = []
    for path in sorted(MUSIC.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
            continue
        k = kind(path)
        if k == "mp4":
            why = mp4_problem(path)
            if why:
                todo.append((path, why, False))
        elif k == "webm":
            todo.append((path, "WebM disfrazado", True))
    if not todo:
        print("Audio: todas las canciones están bien.")
        return 0
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("AVISO: no hay ffmpeg; no se pudieron arreglar", len(todo), "canciones.")
        return 0
    fixed = 0
    for path, why, reencode in todo:
        dst = target_for(path)
        print(f"  {path.relative_to(MUSIC)}  ({why}) → {dst.name}")
        fixed += convert(ffmpeg, path, dst, reencode)
    print(f"Audio: {fixed} de {len(todo)} canciones arregladas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
