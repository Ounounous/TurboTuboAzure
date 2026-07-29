"""
Recodifica las grabaciones de llamada (voz telefonica, banda angosta 300-3400Hz) a Opus mono
16kbps VBR via ffmpeg -- ~4-8x mas chico que el MP3 que entrega pbxip.cl, sin perdida perceptible
(el origen nunca tuvo mas informacion que esa: ver investigacion en el PR/conversacion de deploy).

Requiere el binario `ffmpeg` en el worker de Celery. Si no esta instalado (deploy que todavia no
lo aprovisiono), se degrada solo: devuelve el audio original sin tocar y loguea UNA vez por
proceso, para no arriesgar la descarga de grabaciones (retencion legal 2 anios, Ley 21.320) por
una dependencia de infraestructura que todavia no esta lista.
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG_BIN = shutil.which('ffmpeg')
_missing_ffmpeg_logged = False


def transcode_to_opus(audio_bytes, source_ext='mp3'):
    """Devuelve (bytes_recodificados, extension) o (audio_bytes, source_ext) si ffmpeg no esta
    disponible o si la recodificacion falla (nunca lanza -- el llamador siempre recibe audio
    valido, aunque no haya podido comprimirse)."""
    global _missing_ffmpeg_logged
    if not FFMPEG_BIN:
        if not _missing_ffmpeg_logged:
            logger.warning(
                'audio_compress: ffmpeg no esta instalado en este worker -- las grabaciones se '
                'guardan sin recomprimir (MP3 original de pbxip.cl).'
            )
            _missing_ffmpeg_logged = True
        return audio_bytes, source_ext

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f'in.{source_ext}'
        dst = Path(tmp) / 'out.opus'
        src.write_bytes(audio_bytes)
        try:
            subprocess.run(
                [
                    FFMPEG_BIN, '-y', '-i', str(src),
                    '-ac', '1', '-ar', '8000',           # mono, 8kHz (ancho de banda telefonico real)
                    '-c:a', 'libopus', '-b:a', '16k', '-vbr', 'on', '-application', 'voip',
                    str(dst),
                ],
                capture_output=True, timeout=60, check=True,
            )
            return dst.read_bytes(), 'opus'
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            detail = exc.stderr.decode(errors='replace')[-500:] if getattr(exc, 'stderr', None) else str(exc)
            logger.warning(f'audio_compress: fallo la recodificacion a Opus, se guarda el original. {detail}')
            return audio_bytes, source_ext
