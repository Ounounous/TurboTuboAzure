"""
Filas de telefonos/correos filtrados para las pantallas de Estado de demografia y su export a
Excel. Usado tanto por las vistas (tabla en pantalla) como por el worker del export (ver
demographics/tasks.py), para que "descargar con estos filtros" traiga exactamente lo que se ve.
"""
from django.db.models import Max, Q

from lead.filtering import aplicar_filtros_clientes
from lead.permissions import leads_visibles, scope_por_lead

from .models import AvalDemographics, IDDemographics, Phone

TELEFONOS_HEADERS = ['cartera', 'subcartera', 'op', 'telefono', 'status']
CORREOS_HEADERS = ['cartera', 'subcartera', 'op', 'mail', 'status']


def _leads_filtrados(user, params):
    """Leads visibles para el usuario, con los mismos filtros de la pagina Clientes aplicados
    (columna, rango, dias desde ultima gestion) -- pero SIN el buscador libre 'q', que en estas
    pantallas tiene su propio significado (numero de telefono / correo, no solo op/nombre/rut)."""
    base = leads_visibles(user).annotate(last_action_at=Max('actions__created_at'))
    return aplicar_filtros_clientes(base, params, user)


def telefonos_filtrados(user, params):
    """Mismo criterio que la pantalla Estado de telefonos: buscador libre (numero/ID/nombre) +
    panel avanzado (los mismos filtros de Clientes)."""
    phones = scope_por_lead(Phone.objects.select_related('lead__subcartera__cartera'), user)
    q = (params.get('q') or '').strip()
    if q:
        phones = phones.filter(
            Q(phone_number__icontains=q) | Q(lead__op__icontains=q) | Q(lead__name__icontains=q)
        )
    phones = phones.filter(lead__in=_leads_filtrados(user, params))
    return phones.order_by('lead__op', 'phone_number')


def correos_filtrados(user, params):
    """Mismo criterio que telefonos_filtrados, pero para correos (principal + aval). Devuelve una
    lista de dicts {kind, pk, email, status, lead}, igual que antes ofrecia EmailStatusView."""
    q = (params.get('q') or '').strip()
    leads_qs = _leads_filtrados(user, params)

    idd = scope_por_lead(
        IDDemographics.objects.select_related('lead__subcartera__cartera'), user
    ).exclude(principal_email='')
    avals = scope_por_lead(
        AvalDemographics.objects.select_related('id_demographics__lead__subcartera__cartera'),
        user, lead_field='id_demographics__lead',
    ).exclude(aval_email='').exclude(aval_email__isnull=True)

    if q:
        idd = idd.filter(Q(principal_email__icontains=q) | Q(lead__op__icontains=q) | Q(lead__name__icontains=q))
        avals = avals.filter(
            Q(aval_email__icontains=q) | Q(id_demographics__lead__op__icontains=q)
            | Q(id_demographics__lead__name__icontains=q)
        )

    idd = idd.filter(lead__in=leads_qs)
    avals = avals.filter(id_demographics__lead__in=leads_qs)

    items = []
    for d in idd:
        items.append({'kind': 'principal', 'pk': d.pk, 'email': d.principal_email,
                      'status': d.principal_email_status, 'lead': d.lead})
    for a in avals:
        items.append({'kind': 'aval', 'pk': a.pk, 'email': a.aval_email,
                      'status': a.aval_email_status, 'lead': a.id_demographics.lead})
    items.sort(key=lambda x: (x['lead'].op if x['lead'] else '', x['email']))
    return items


def filas_telefonos(phones_qs):
    """Una fila por telefono: cartera, subcartera, op, telefono, status."""
    for phone in phones_qs:
        lead = phone.lead
        yield [
            lead.subcartera.cartera.nombre, lead.subcartera.nombre, lead.op,
            phone.phone_number, phone.phone_number_status,
        ]


def filas_correos(email_items):
    """Una fila por correo (principal o aval): cartera, subcartera, op, mail, status."""
    for item in email_items:
        lead = item['lead']
        yield [
            lead.subcartera.cartera.nombre, lead.subcartera.nombre, lead.op,
            item['email'], item['status'],
        ]
