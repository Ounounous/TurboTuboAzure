"""
Capa de envio de los reportes automaticos (ver actions/models.py: ReporteAutomaticoConfig y
actions/reportes_automaticos.py). Escrito contra la API estandar de django.core.mail.EmailMessage
a proposito: cambiar el backend (SMTP de la casilla del cliente -> Azure Communication Services el
dia de manana) es solo configuracion en turbotubo/settings.py, no reescribir esta funcion.
"""
from django.core.mail import EmailMessage


def enviar_email_reporte(config, fecha_desde, fecha_hasta, filename, contenido_bytes, content_type):
    """Arma y envia el correo del reporte. No captura excepciones -- el caller
    (actions/tasks.py::enviar_reporte_automatico) decide que hacer con un fallo de envio."""
    if config.asunto_personalizado:
        asunto = config.asunto_personalizado
    elif fecha_desde == fecha_hasta:
        asunto = f'Reporte de gestiones {config.cartera.nombre} - {fecha_desde:%d-%m-%Y}'
    else:
        asunto = f'Reporte de gestiones {config.cartera.nombre} - {fecha_desde:%d-%m-%Y} a {fecha_hasta:%d-%m-%Y}'

    cuerpo = (
        f'Reporte automático de gestiones de la cartera {config.cartera.nombre}.\n\n'
        f'Periodo: {fecha_desde:%d-%m-%Y} a {fecha_hasta:%d-%m-%Y}.\n\n'
        f'Este correo se generó y envió automáticamente desde TurboTubo.'
    )

    email = EmailMessage(
        subject=asunto,
        body=cuerpo,
        from_email=config.remitente_from or None,
        to=config.to_list(),
        cc=config.cc_list() or None,
        bcc=config.cco_list() or None,
    )
    email.attach(filename, contenido_bytes, content_type)
    email.send(fail_silently=False)
