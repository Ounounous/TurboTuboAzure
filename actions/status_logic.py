"""
Motor de status del lead: el status deja de editarse a mano (salvo "Al dia" por un supervisor,
ver lead.views.MarcarAlDiaView) y se calcula solo a partir de las gestiones (Action) y los pagos
(Payment) reales. Las reglas fueron validadas fila por fila sobre los arboles de gestion de
Galgo, Tanner y Nuevo Capital.
"""
from lead.models import Lead, StatusChangeLog


def compute_status(resultado, fecha_compromiso):
    """Status que corresponde al lead segun el resultado de una gestion recien guardada."""
    from .models import Resultado

    if resultado.efecto_pago == Resultado.EFECTO_AL_DIA:
        return Lead.AL_DIA
    if resultado.efecto_pago == Resultado.EFECTO_PAGANDO:
        return Lead.PAGANDO
    if resultado.crea_compromiso and fecha_compromiso:
        return Lead.COMPROMISO
    if resultado.contactabilidad == Resultado.CON_CONTACTO:
        return Lead.CONTACTADO
    return Lead.NO_CONTACTADO


def apply_status(lead, new_status, changed_by=None):
    """Actualiza status actual + historico (si new_status es mejor) y deja registro en el log."""
    lead.status = new_status
    if Lead.STATUS_RANK[new_status] > Lead.STATUS_RANK.get(lead.status_historico, 0):
        lead.status_historico = new_status
    lead.save(update_fields=['status', 'status_historico'])
    StatusChangeLog.objects.create(lead=lead, changed_by=changed_by, new_status=new_status)

    # "Al dia" = pago toda la deuda -> el lead pasa a terminado (ciclo de vida). Cubre tanto el
    # "marcar al dia" manual del supervisor como el resultado Galgo PAGO / AL DIA.
    if new_status == Lead.AL_DIA and lead.activo != Lead.TERMINADO:
        from lead.lifecycle import terminar
        terminar(lead, changed_by=changed_by)


def _tiene_contacto_activo(lead):
    """True si al lead le queda algun telefono o correo en estado 'activo'. Una sola query
    (tres EXISTS correlacionados en un unico round-trip, en vez de 3 consultas separadas)."""
    from django.db.models import Exists, OuterRef, Q
    from demographics.models import Phone, IDDemographics, AvalDemographics, Email, CONTACT_ACTIVE

    return Lead.objects.filter(pk=lead.pk).annotate(
        _tel=Exists(Phone.objects.filter(lead=OuterRef('pk'), phone_number_status=CONTACT_ACTIVE)),
        _mail=Exists(IDDemographics.objects.filter(
            lead=OuterRef('pk'), principal_email_status=CONTACT_ACTIVE).exclude(principal_email='')),
        _mail2=Exists(Email.objects.filter(lead=OuterRef('pk'), email_status=CONTACT_ACTIVE)),
        _aval=Exists(AvalDemographics.objects.filter(
            id_demographics__lead=OuterRef('pk'), aval_email_status=CONTACT_ACTIVE,
        ).exclude(aval_email='').exclude(aval_email__isnull=True)),
    ).filter(Q(_tel=True) | Q(_mail=True) | Q(_mail2=True) | Q(_aval=True)).exists()


def recompute_inubicable(lead, changed_by=None):
    """
    Marca/desmarca 'inubicable' segun si al lead le queda algun dato de contacto activo. Solo
    actua cuando el lead sigue en 'no contactado'/'recien asignado' (no pisa un lead que ya fue
    contactado o que avanzo mas). Inubicable = no contactado + sin datos que sirvan.
    """
    tiene = _tiene_contacto_activo(lead)
    if not tiene and lead.status in (Lead.RECIEN_ASIGNADO, Lead.NO_CONTACTADO):
        apply_status(lead, Lead.INUBICABLE, changed_by)
    elif tiene and lead.status == Lead.INUBICABLE:
        apply_status(lead, Lead.NO_CONTACTADO, changed_by)


def aplicar_efecto_demografico(action):
    """
    Aplica el efecto del resultado de una gestion sobre el dato de contacto usado (el telefono o
    el correo): lo marca no existe / fuera de servicio / blacklist, y/o le apaga WhatsApp. Luego
    recalcula si el lead quedo inubicable.
    """
    from demographics.models import IDDemographics, AvalDemographics

    resultado = action.resultado
    if not resultado:
        return

    efecto = resultado.efecto_demografia
    apaga_wa = resultado.desactiva_whatsapp
    nuevo_status = resultado.efecto_demografia_status()  # '' o el valor de phone_number_status

    if action.phone_id:
        phone = action.phone
        campos = []
        if nuevo_status:
            phone.phone_number_status = nuevo_status
            campos.append('phone_number_status')
        if apaga_wa:
            phone.whatsapp_activo = False
            campos.append('whatsapp_activo')
        if campos:
            phone.save(update_fields=campos)
    elif action.email and nuevo_status:
        # El correo vive como texto en la demografia; se marca la fila que coincide (principal,
        # aval o adicional).
        from demographics.models import Email
        IDDemographics.objects.filter(lead=action.lead, principal_email=action.email).update(
            principal_email_status=nuevo_status
        )
        AvalDemographics.objects.filter(
            id_demographics__lead=action.lead, aval_email=action.email
        ).update(aval_email_status=nuevo_status)
        Email.objects.filter(lead=action.lead, email=action.email).update(email_status=nuevo_status)

    if efecto or apaga_wa:
        recompute_inubicable(action.lead, changed_by=action.user)
