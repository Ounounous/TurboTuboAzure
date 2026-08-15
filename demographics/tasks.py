import logging
from io import BytesIO

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import InterfaceError, OperationalError
from django.http import QueryDict
from django.utils import timezone
from openpyxl import Workbook

logger = logging.getLogger(__name__)

# Reintentos con backoff exponencial ante errores transitorios de BD (conexion caida/reinicio).
# Mismo patron que actions/tasks.py -- sin esto, un hipo de Postgres manda el job directo a ERROR
# en vez de reintentarse solo, y el usuario tiene que volver a pedir el export a mano.
RETRY_DB = dict(
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)


@shared_task(**RETRY_DB)
def generar_export_contactos(job_id):
    """
    Arma el Excel de telefonos o correos filtrados en el WORKER: con miles de filas (una por
    telefono/correo, no por lead) la consulta y el armado del archivo pueden superar el limite de
    espera del proxy de Azure si se hicieran en el proceso web.
    """
    from .exports import (
        CORREOS_HEADERS, TELEFONOS_HEADERS, correos_filtrados, filas_correos,
        filas_telefonos, telefonos_filtrados,
    )
    from .models import ContactExportJob

    try:
        job = ContactExportJob.objects.select_related('solicitado_por').get(pk=job_id)
    except ContactExportJob.DoesNotExist:
        logger.warning(f"generar_export_contactos: job {job_id} no existe (¿se borró?)")
        return

    job.estado = ContactExportJob.PROCESANDO
    job.save(update_fields=['estado'])

    try:
        params = QueryDict(job.filtros or '')
        if job.tipo == ContactExportJob.TELEFONOS:
            headers = TELEFONOS_HEADERS
            filas = filas_telefonos(telefonos_filtrados(job.solicitado_por, params))
        else:
            headers = CORREOS_HEADERS
            filas = filas_correos(correos_filtrados(job.solicitado_por, params))

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        total = 0
        for fila in filas:
            ws.append(fila)
            total += 1

        job.total_filas = total
        if total == 0:
            job.estado = ContactExportJob.VACIO
            job.mensaje = 'No hay datos con esos filtros.'
        else:
            output = BytesIO()
            wb.save(output)
            job.archivo.save(f"{job.tipo}_{job.pk}.xlsx", ContentFile(output.getvalue()), save=False)
            job.estado = ContactExportJob.LISTO
            job.mensaje = f'{total} fila(s).'
    except Exception:
        logger.exception(f"generar_export_contactos: falló el job {job_id}")
        job.estado = ContactExportJob.ERROR
        job.mensaje = 'Falla del servidor generando el archivo. Reintenta o avisa a soporte.'

    job.finished_at = timezone.now()
    job.save(update_fields=['estado', 'total_filas', 'mensaje', 'archivo', 'finished_at'])
