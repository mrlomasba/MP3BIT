"""Genera songs.json (y las portadas en covers/) a partir de la carpeta music/.

Uso:  python scripts/build_catalog.py

- Cada subcarpeta de music/ se muestra como una playlist.
- Si está instalado `mutagen` (pip install mutagen) se leen título, artista,
  álbum, duración y portada de las etiquetas del archivo. Si no, el título
  sale del nombre del archivo ("Artista - Título.mp3").
- Si una carpeta tiene cover.jpg / folder.jpg / cover.png, se usa como portada
  para las canciones que no traen una propia.
- Las canciones del songs.json anterior que ya no están en music/ se conservan
  (ya están publicadas en GitHub): puedes borrarlas del PC tras subirlas.
- Para quitar una del catálogo:  python scripts/build_catalog.py --quitar "nombre"
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC = ROOT / "music"
COVERS = ROOT / "covers"
OUT = ROOT / "songs.json"
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
FOLDER_COVERS = ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg", "folder.png", "front.jpg")

try:
    import mutagen  # type: ignore
    from mutagen.id3 import ID3  # type: ignore
except Exception:  # pragma: no cover
    mutagen = None


def tag(tags, *keys):
    if not tags:
        return None
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v:
            v = v[0] if isinstance(v, list) else v
            v = getattr(v, "text", v)
            if isinstance(v, list):
                v = v[0] if v else None
            if v:
                return str(v).strip()
    return None


def read_meta(path: Path) -> dict:
    meta: dict = {}
    if not mutagen:
        return meta
    try:
        f = mutagen.File(path)
    except Exception:
        return meta
    if f is None:
        return meta
    if getattr(f, "info", None) and getattr(f.info, "length", None):
        meta["duration"] = round(float(f.info.length), 1)
    tags = f.tags
    meta["title"] = tag(tags, "TIT2", "title", "\xa9nam", "TITLE")
    meta["artist"] = tag(tags, "TPE1", "artist", "\xa9ART", "ARTIST", "TPE2", "aART")
    meta["album"] = tag(tags, "TALB", "album", "\xa9alb", "ALBUM")
    tn = tag(tags, "TRCK", "tracknumber", "TRACKNUMBER")
    if tn:
        m = re.match(r"\d+", tn)
        if m:
            meta["track"] = int(m.group())
    if not tn and tags is not None and "trkn" in tags:
        try:
            meta["track"] = int(tags["trkn"][0][0])
        except Exception:
            pass

    # Portada incrustada
    img, ext = None, "jpg"
    try:
        if isinstance(tags, ID3):
            for k in tags.keys():
                if k.startswith("APIC"):
                    apic = tags[k]
                    img = apic.data
                    ext = "png" if "png" in (apic.mime or "") else "jpg"
                    break
        elif tags is not None and "covr" in tags and tags["covr"]:
            c = tags["covr"][0]
            img = bytes(c)
            ext = "png" if getattr(c, "imageformat", 13) == 14 else "jpg"
        elif getattr(f, "pictures", None):
            p = f.pictures[0]
            img = p.data
            ext = "png" if "png" in (p.mime or "") else "jpg"
    except Exception:
        img = None
    if img:
        # Nombre según el contenido: las canciones de un mismo álbum comparten
        # un único archivo, y si la portada cambia, cambia el nombre (sin cachés viejas).
        COVERS.mkdir(exist_ok=True)
        name = f"{hashlib.sha1(img).hexdigest()[:16]}.{ext}"
        if not (COVERS / name).exists():
            (COVERS / name).write_bytes(img)
        meta["cover"] = f"covers/{name}"
    return {k: v for k, v in meta.items() if v}


def from_filename(stem: str) -> tuple[str | None, str]:
    stem = re.sub(r"^\d{1,3}[\s._-]+", "", stem).strip()  # quita "01 - "
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return None, stem


def load_previous() -> list[dict]:
    """Canciones del songs.json anterior (las que ya se publicaron)."""
    if not OUT.exists():
        return []
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return [t for t in data.get("tracks", []) if isinstance(t, dict) and t.get("file") and t.get("id")]
    except Exception:
        print("AVISO: songs.json está dañado; se genera solo con lo que hay en music/.")
        return []


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def write_catalog(tracks: list[dict]) -> None:
    tracks.sort(key=lambda t: (
        (t.get("folder") or "").lower(),
        (t.get("album") or "").lower(),
        t.get("track") or 9999,
        t["title"].lower(),
    ))
    if tracks == load_previous() and OUT.exists():
        return  # sin cambios: no se reescribe (así GitHub no hace commits vacíos)
    OUT.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(tracks),
        "tracks": tracks,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def remove(text: str) -> int:
    """Quita del catálogo las canciones cuyo título, artista o archivo contengan `text`."""
    tracks = load_previous()
    q = norm(text.strip())
    if not q:
        print('Escribe parte del nombre: npm run quitar -- "nombre de la canción"')
        return 1
    hits = [t for t in tracks if q in norm(" ".join(str(t.get(k) or "") for k in ("title", "artist", "file")))]
    if not hits:
        print(f'No hay ninguna canción que contenga «{text}». No se cambió nada.')
        return 1
    write_catalog([t for t in tracks if t not in hits])
    print(f"Quitadas del catálogo ({len(hits)}):")
    for t in hits:
        print(f"  - {t['file']}")
        if (ROOT / t["file"]).exists():
            print("    AVISO: sigue en tu carpeta music/; bórrala de ahí o volverá a aparecer.")
    print('Ahora ejecuta "npm run dist" y sube dist/songs.json a GitHub.')
    print("(El MP3 puede quedarse en GitHub sin problema, o bórralo allí para liberar espacio.)")
    return 0


def main() -> int:
    if "--quitar" in sys.argv:
        return remove(" ".join(sys.argv[sys.argv.index("--quitar") + 1:]))
    if not MUSIC.exists():
        MUSIC.mkdir()

    previous = load_previous()
    tracks = []
    for path in sorted(MUSIC.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
            continue
        rel = path.relative_to(ROOT).as_posix()
        track_id = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
        folder_parts = path.relative_to(MUSIC).parent.parts
        folder = " / ".join(folder_parts) if folder_parts else None

        meta = read_meta(path)
        fn_artist, fn_title = from_filename(path.stem)
        t = {
            "id": track_id,
            "file": rel,
            "title": meta.get("title") or fn_title,
            "artist": meta.get("artist") or fn_artist,
            "album": meta.get("album"),
            "folder": folder,
            "track": meta.get("track"),
            "duration": meta.get("duration"),
            "size": path.stat().st_size,
            "cover": meta.get("cover"),
        }
        if not t["cover"]:
            for name in FOLDER_COVERS:
                c = path.parent / name
                if c.exists():
                    t["cover"] = c.relative_to(ROOT).as_posix()
                    break
        tracks.append({k: v for k, v in t.items() if v is not None})

    # Las canciones ya publicadas que ya no están en el PC se conservan: siguen en GitHub.
    # Si una se movió de carpeta (mismo nombre y tamaño), cuenta la ubicación nueva.
    # Con --completo (lo usa GitHub, que tiene toda la música) no se conserva nada: lo borrado se quita.
    local_files = {t["file"] for t in tracks}
    local_keys = {(Path(t["file"]).name, t["size"]) for t in tracks}
    kept = [] if "--completo" in sys.argv else [
        t for t in previous
        if t["file"] not in local_files and (Path(t["file"]).name, t.get("size")) not in local_keys]
    tracks += kept

    # Portadas: se borran solo las que ya no usa ninguna canción
    used = {t.get("cover") for t in tracks}
    if COVERS.exists():
        for p in COVERS.iterdir():
            if p.is_file() and f"covers/{p.name}" not in used:
                p.unlink()

    write_catalog(tracks)

    total = sum(t.get("size", 0) for t in tracks)
    print(f"songs.json: {len(tracks)} canciones, {total / 1024 / 1024:.1f} MB"
          + ("" if mutagen else "  (sin mutagen: no se leyeron etiquetas)"))
    print(f"  {len(tracks) - len(kept)} en music/ de este PC · {len(kept)} ya publicadas (se conservan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
