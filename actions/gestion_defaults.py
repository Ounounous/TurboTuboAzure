"""
Defaults del formulario manual de gestion ("un click final"): al elegir un medio (Llamar /
WhatsApp / Correo), se preselecciona el resultado mas probable -- el cobrador igual puede
cambiarlo antes de grabar. Y el filtro de resultados visibles para cobrador en Tanner/Nuevo
Capital (solo Directo + Sin contacto; nada de Indirecto/Directo aval/Accion masiva/Recibidos).

Nada de esto toca el arbol de gestiones (Medio/Resultado) ni bloquea la carga masiva -- son solo
recortes/preselecciones sobre el formulario manual de un cobrador.
"""
from lead.models import Lead


def _medio(cartera, nombre):
    from .models import Medio
    return Medio.objects.filter(cartera=cartera, nombre__iexact=nombre).first()


def _resultado(cartera, **kwargs):
    from .models import Resultado
    return Resultado.objects.filter(cartera=cartera, **kwargs).first()


def resultados_default_por_medio(cartera, lead=None):
    """{medio_id: resultado_id} para la cartera dada. Si no hay match para un medio, no se
    preselecciona nada y el cobrador elige a mano como siempre.

    `lead` solo hace falta para Tanner: el default de WhatsApp/Correo ("OTROS" / Directo) solo
    aplica si el lead SIGUE "no contactado" -- si ya avanzo (contactado, compromiso, etc.) seria
    una suposicion equivocada, asi que ahi no se preselecciona nada.
    """
    nombre_cartera = (cartera.nombre or '').strip()
    defaults = {}

    if nombre_cartera == 'Galgo':
        contacto = _resultado(cartera, nombre__iexact='MSJ DE CONTACTO')
        no_responde = _resultado(cartera, nombre__iexact='NO RESPONDE')
        if contacto:
            for medio_nombre in ('WHATSAPP', 'EMAIL'):
                medio = _medio(cartera, medio_nombre)
                if medio:
                    defaults[medio.id] = contacto.id
        medio_llamada = _medio(cartera, 'TELEFONICO')
        if medio_llamada and no_responde:
            defaults[medio_llamada.id] = no_responde.id

    elif nombre_cartera == 'Nuevo Capital':
        wa_entregado = _resultado(
            cartera, nombre__iexact='ENVIO WHATSAPP ENTREGADO', tipo_contacto='SIN CONTACTO',
        )
        mail_entregado = _resultado(
            cartera, nombre__iexact='ENVIO EMAIL ENTREGADO', tipo_contacto='SIN CONTACTO',
        )
        no_contesta = _resultado(cartera, nombre__iexact='NO CONTESTA', tipo_contacto='SIN CONTACTO')
        medio_wa = _medio(cartera, 'WHATSAPP')
        medio_correo = _medio(cartera, 'CORREO')
        medio_llamada = _medio(cartera, 'LLAMADA')
        if medio_wa and wa_entregado:
            defaults[medio_wa.id] = wa_entregado.id
        if medio_correo and mail_entregado:
            defaults[medio_correo.id] = mail_entregado.id
        if medio_llamada and no_contesta:
            defaults[medio_llamada.id] = no_contesta.id

    elif nombre_cartera == 'Tanner':
        no_contesta_operador = _resultado(
            cartera, nombre__iexact='SIN CONTACTO NO CONTESTA', tipo_contacto='SIN CONTACTO OPERADOR',
        )
        medio_llamada = _medio(cartera, 'Manual')
        if medio_llamada and no_contesta_operador:
            defaults[medio_llamada.id] = no_contesta_operador.id

        if lead is not None and lead.status == Lead.NO_CONTACTADO:
            directo_otros = _resultado(cartera, nombre__iexact='OTROS', tipo_contacto='DIRECTO')
            if directo_otros:
                medio_wa = _medio(cartera, 'WhatsApp')
                medio_correo = _medio(cartera, 'Email')
                if medio_wa:
                    defaults[medio_wa.id] = directo_otros.id
                if medio_correo:
                    defaults[medio_correo.id] = directo_otros.id

    return defaults


# tipo_contacto que puede elegir un COBRADOR en el formulario manual, por cartera. Solo Directo
# (no Directo aval) y Sin contacto (todas las variantes) -- nada de Indirecto/Accion masiva/
# Sin gestion. admin/owner/supervisor siguen viendo la lista completa (pueden necesitar corregir
# o registrar cualquier resultado). No aplica a Galgo (no lo pidieron, y Galgo no usa tipo_contacto).
TIPO_CONTACTO_COLLECTOR_WHITELIST = {
    'Tanner': ['DIRECTO', 'SIN CONTACTO OPERADOR', 'SIN CONTACTO MAQUINA', 'SIN CONTACTO TERRENO'],
    'Nuevo Capital': ['DIRECTO', 'SIN CONTACTO'],
}
