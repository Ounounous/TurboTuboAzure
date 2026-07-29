"""
Export periodico de la metadata anonimizada a JSONL, un archivo por corrida, al storage de
mlmetadata/storage.py (Azure Blob en un contenedor separado en produccion, disco local en dev).
Una vez que el archivo quedo escrito en el blob, las filas exportadas se BORRAN de Postgres
(no solo se marcan): a 4500 gestiones/dia esta tabla crece ~1.5-2GB cada 2 anios si nunca se
purga, y esa informacion ya vive, integra, en el JSONL del blob -- no hace falta duplicarla
indefinidamente en la base transaccional. exportado_at se sigue seteando primero (paso
intermedio) por si el borrado fallara a mitad de camino: nunca se pierde una fila sin que su
export haya quedado confirmado en el blob primero.

Programacion real (cron) via /admin -> Periodic Tasks (django-celery-beat), igual que el resto
de tareas periodicas de este proyecto.
"""
import gzip
import json
import logging
import uuid
from io import BytesIO

from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from .models import CicloVidaEvento, GestionEvento, PagoEvento
from .storage import get_ml_storage

logger = logging.getLogger(__name__)

RETRY_DB = dict(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)

EXPORT_SPECS = {
    'gestiones': (GestionEvento, [
        'lead_token', 'cartera_token', 'cobrador_token', 'secuencia', 'dias_desde_creacion_lead',
        'dia_semana', 'dia_del_mes', 'franja_horaria', 'canal', 'es_llamada', 'es_inbound',
        'target', 'contactabilidad', 'tipo_contacto', 'crea_compromiso', 'requiere_fecha_pago',
        'efecto_pago', 'dias_hasta_compromiso', 'status_antes', 'status_despues', 'ciclo_cartera',
        'ciclo', 'tipo_cobranza', 'tiene_aval', 'saldo_insoluto', 'cuotas_atrasadas', 'created_at',
    ]),
    'pagos': (PagoEvento, [
        'lead_token', 'cartera_token', 'monto', 'tipo', 'dia_semana', 'dia_del_mes',
        'dias_desde_ultima_gestion', 'dias_vs_compromiso', 'status_antes', 'status_despues',
        'created_at',
    ]),
    'ciclo_vida': (CicloVidaEvento, [
        'lead_token', 'cartera_token', 'tipo_transicion', 'dias_desde_creacion_lead', 'created_at',
    ]),
}


def _serializable(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _fila(obj, campos):
    return {campo: _serializable(getattr(obj, campo)) for campo in campos}


@shared_task(**RETRY_DB)
def exportar_metadata_ml():
    """Exporta lo no exportado de cada tabla de eventos a un JSONL propio. Devuelve un dict
    {nombre: filas_exportadas} para el log de Celery."""
    storage = get_ml_storage()
    ahora = timezone.now()
    sello = ahora.strftime('%Y%m%d-%H%M%S')
    resumen = {}

    for nombre, (modelo, campos) in EXPORT_SPECS.items():
        pendientes = modelo.objects.filter(exportado_at__isnull=True).order_by('pk')
        ids = list(pendientes.values_list('pk', flat=True))
        if not ids:
            resumen[nombre] = 0
            continue

        # Gzip: JSONL es texto muy repetitivo (mismos nombres de campo en cada linea), asi que
        # comprime ~10x -- a 4500 gestiones/dia serian ~1.8GB/2 anios sin comprimir vs ~0.2GB
        # comprimido en Blob Storage, por el mismo costo de CPU casi nulo.
        buf = BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
            for obj in pendientes.iterator():
                gz.write(json.dumps(_fila(obj, campos), ensure_ascii=False).encode('utf-8'))
                gz.write(b'\n')
        buf.seek(0)

        path = storage.save(f'{nombre}/{sello}.jsonl.gz', buf)
        # Primero se marca (si el borrado de abajo fallara a mitad de camino, la fila queda
        # identificable como "ya exportada, pendiente de limpieza" en vez de perderse sin rastro).
        modelo.objects.filter(pk__in=ids).update(exportado_at=ahora)
        # El JSONL en el blob ya tiene esta fila completa: se borra de Postgres para no duplicar
        # el dato indefinidamente en la base transaccional (ver docstring del modulo).
        modelo.objects.filter(pk__in=ids).delete()
        resumen[nombre] = len(ids)
        logger.info('mlmetadata: exportadas y purgadas %s filas de %s a %s', len(ids), nombre, path)

    return resumen
