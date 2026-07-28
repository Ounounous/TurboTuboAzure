import re
import unicodedata
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from openpyxl import Workbook, load_workbook
from lead.models import Lead
from lead.permissions import scope_por_lead
from .models import (
    IDItem, Phone, IDDemographics, AvalDemographics,
    CHOICES_CONTACT_STATUS, CONTACT_BLACKLISTED, CONTACT_NON_EXISTENT, CONTACT_OUT_OF_SERVICE,
)

SUPERVISOR_TYPES = ('admin', 'owner', 'supervisor')

# Acepta lo que el usuario escriba (español/inglés) para el estado de un dato de contacto.
_STATUS_ALIASES = {
    'active': 'active', 'activo': 'active', 'activa': 'active',
    'non existent': 'non-existent', 'non-existent': 'non-existent', 'no existe': 'non-existent',
    'noexiste': 'non-existent', 'inexistente': 'non-existent',
    'out of service': 'out of service', 'fuera de servicio': 'out of service', 'fuera servicio': 'out of service',
    'blacklisted': 'blacklisted', 'blacklist': 'blacklisted', 'lista negra': 'blacklisted',
}


def _norm_status(value):
    """Normaliza el texto de un estado a su valor canonico, o '' si no es reconocible."""
    v = str(value or '').strip().lower()
    v = ''.join(c for c in unicodedata.normalize('NFKD', v) if not unicodedata.combining(c))
    v = re.sub(r'[_\-]+', ' ', v)
    v = ' '.join(v.split())
    if v in _STATUS_ALIASES:
        return _STATUS_ALIASES[v]
    # tolera guiones ("non-existent")
    return _STATUS_ALIASES.get(v.replace(' ', '-'), '')


class SupervisorRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        userprofile = getattr(request.user, 'userprofile', None)
        if not userprofile or userprofile.user_type not in SUPERVISOR_TYPES:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _recompute_inubicable_bulk(lead_pks, user):
    """Recalcula inubicable de los leads cuya demografia se acaba de cargar/cambiar."""
    if not lead_pks:
        return
    from actions.status_logic import recompute_inubicable
    for lead in Lead.objects.filter(pk__in=lead_pks):
        recompute_inubicable(lead, changed_by=user)

TEMPLATE_SPECS = {
    'phone': {
        'filename': 'plantilla_telefonos.xlsx',
        'headers': ['cartera', 'subcartera', 'op', 'phone_number', 'phone_type', 'phone_status'],
        'example': ['CARTERA-EJEMPLO', 'SUBCARTERA-EJEMPLO', 'OP-EJEMPLO', '+56912345678', 'principal', 'active'],
    },
    'iddemographics': {
        'filename': 'plantilla_email.xlsx',
        'headers': ['cartera', 'subcartera', 'op', 'principal_email'],
        'example': ['CARTERA-EJEMPLO', 'SUBCARTERA-EJEMPLO', 'OP-EJEMPLO', 'ejemplo@correo.com'],
    },
    'address': {
        'filename': 'plantilla_direccion.xlsx',
        'headers': ['cartera', 'subcartera', 'op', 'principal_address'],
        'example': ['CARTERA-EJEMPLO', 'SUBCARTERA-EJEMPLO', 'OP-EJEMPLO', 'Calle Falsa 123'],
    },
    'iditem': {
        'filename': 'plantilla_bienes.xlsx',
        'headers': ['cartera', 'subcartera', 'op', 'item_type', 'patente', 'marca', 'modelo', 'año'],
        'example': ['CARTERA-EJEMPLO', 'SUBCARTERA-EJEMPLO', 'OP-EJEMPLO', 'auto', 'AB1234', 'Toyota', 'Yaris', 2020],
    },
}


class DownloadTemplateView(SupervisorRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        spec = TEMPLATE_SPECS.get(kwargs.get('form_type'))
        if not spec:
            raise Http404

        wb = Workbook()
        ws = wb.active
        ws.append(spec['headers'])
        ws.append(spec['example'])

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename={spec["filename"]}'
        return response


EMAIL_COLUMN_ALIASES = {'principal_email', 'email', 'mail', 'correo', 'correo_electronico'}


def _normalize_header(value):
    value = str(value or '').strip().lower()
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '_', value).strip('_')


def find_lead(cartera, subcartera, op):
    cartera = str(cartera).strip() if cartera is not None else ''
    subcartera = str(subcartera).strip() if subcartera is not None else ''
    op = str(op).strip() if op is not None else ''
    return Lead.objects.filter(
        op__iexact=op,
        subcartera__cartera__nombre__iexact=cartera,
        subcartera__nombre__iexact=subcartera,
    ).first()


class DemographicsIndexView(SupervisorRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        form_type = request.GET.get('form_type', None)
        return render(request, 'demographics/demographics_index.html', {'form_type': form_type})


ITEM_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'item_type': 'item_type', 'tipo': 'item_type', 'tipo_bien': 'item_type',
    'patente': 'patente', 'marca': 'marca', 'modelo': 'modelo',
    'ano': 'anio', 'anio': 'anio', 'year': 'anio',
}


class UploadIDItemView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')

            tipos_validos = dict(IDItem.CHOICES_ITEM_TYPE)
            tipo_raw = str(fila.get('item_type') or '').strip().lower()
            tipo = tipo_raw if tipo_raw in tipos_validos else IDItem.AUTO
            if tipo_raw and tipo_raw not in tipos_validos:
                errores.append(f'tipo de bien: "{fila.get("item_type")}" inválido ({"/".join(tipos_validos)})')

            anio_raw = fila.get('anio')
            anio = None
            if anio_raw not in (None, ''):
                try:
                    anio = int(anio_raw)
                except (TypeError, ValueError):
                    errores.append(f'año: "{anio_raw}" no es un número')

            if errores:
                return None, errores
            return {
                'lead': lead, 'tipo': tipo, 'anio': anio,
                'patente': str(fila.get('patente') or '').strip(),
                'marca': str(fila.get('marca') or '').strip(),
                'modelo': str(fila.get('modelo') or '').strip(),
            }, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), ITEM_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op'), validar_fila,
            nombre_archivo='errores_bienes.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        with transaction.atomic():
            for f in resultado.filas:
                id_item, _ = IDItem.objects.get_or_create(lead=f['lead'])
                id_item.item_type = f['tipo']
                id_item.patente = f['patente']
                id_item.marca = f['marca']
                id_item.modelo = f['modelo']
                id_item.año = f['anio']
                id_item.save()

        messages.success(request, f"{len(resultado.filas)} bien(es) cargado(s) correctamente.")
        return redirect('demographics:index')


PHONE_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'phone_number': 'phone_number', 'telefono': 'phone_number', 'numero': 'phone_number', 'fono': 'phone_number',
    'phone_type': 'phone_type', 'tipo': 'phone_type',
    'phone_status': 'phone_status', 'estado': 'phone_status', 'status': 'phone_status',
}


class UploadPhoneView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            numero = str(fila.get('phone_number') or '').strip()
            if not numero:
                errores.append('teléfono: vacío')
            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')

            tipo_raw = str(fila.get('phone_type') or '').strip().lower()
            tipo = Phone.AVAL if tipo_raw in ('aval',) else Phone.PRINCIPAL
            if tipo_raw and tipo_raw not in ('principal', 'aval'):
                errores.append(f'tipo: "{fila.get("phone_type")}" inválido (principal/aval)')

            estado_raw = fila.get('phone_status')
            estado = _norm_status(estado_raw) if estado_raw not in (None, '') else Phone.ACTIVE
            if estado_raw not in (None, '') and not estado:
                errores.append(f'estado: "{estado_raw}" inválido (activo/no existe/fuera de servicio/blacklist)')

            if errores:
                return None, errores
            return {'lead': lead, 'numero': numero, 'tipo': tipo, 'estado': estado}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), PHONE_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'phone_number'), validar_fila,
            nombre_archivo='errores_telefonos.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        leads_tocados = set()
        with transaction.atomic():
            for f in resultado.filas:
                phone, _ = Phone.objects.get_or_create(lead=f['lead'], phone_number=f['numero'])
                phone.phone_type = f['tipo']
                phone.phone_number_status = f['estado']
                phone.save()
                leads_tocados.add(f['lead'].pk)
            _recompute_inubicable_bulk(leads_tocados, request.user)

        messages.success(request, f"{len(resultado.filas)} teléfono(s) cargado(s) correctamente.")
        return redirect('demographics:index')


EMAIL_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'principal_email': 'email', 'email': 'email', 'mail': 'email',
    'correo': 'email', 'correo_electronico': 'email',
}


class UploadIDDemographicsView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            correo = str(fila.get('email') or '').strip()
            if not correo:
                errores.append('correo: vacío')
            elif '@' not in correo:
                errores.append(f'correo: "{correo}" no parece un email válido')
            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')
            if errores:
                return None, errores
            return {'lead': lead, 'correo': correo}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), EMAIL_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'email'), validar_fila,
            nombre_archivo='errores_correos.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        leads_tocados = set()
        with transaction.atomic():
            for f in resultado.filas:
                idd, _ = IDDemographics.objects.get_or_create(lead=f['lead'])
                idd.principal_email = f['correo']
                idd.save()
                leads_tocados.add(f['lead'].pk)
            _recompute_inubicable_bulk(leads_tocados, request.user)

        messages.success(request, f"{len(resultado.filas)} email(s) cargado(s) correctamente.")
        return redirect('demographics:index')


ADDRESS_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'principal_address': 'direccion', 'direccion': 'direccion', 'address': 'direccion',
}


class UploadAddressView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            direccion = str(fila.get('direccion') or '').strip()
            if not direccion:
                errores.append('dirección: vacía')
            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')
            if errores:
                return None, errores
            return {'lead': lead, 'direccion': direccion}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), ADDRESS_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'direccion'), validar_fila,
            nombre_archivo='errores_direccion.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        with transaction.atomic():
            for f in resultado.filas:
                id_demographics, _ = IDDemographics.objects.get_or_create(lead=f['lead'])
                id_demographics.principal_address = f['direccion']
                id_demographics.save()

        messages.success(request, f"{len(resultado.filas)} dirección(es) cargada(s) correctamente.")
        return redirect('demographics:index')


AVAL_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'aval_name': 'aval_name', 'nombre_aval': 'aval_name', 'nombre': 'aval_name',
    'aval_rut': 'aval_rut', 'rut_aval': 'aval_rut', 'rut': 'aval_rut',
    'aval_dv': 'aval_dv', 'dv_aval': 'aval_dv', 'dv': 'aval_dv',
    'aval_email': 'aval_email', 'email_aval': 'aval_email', 'correo_aval': 'aval_email',
    'aval_address': 'aval_address', 'direccion_aval': 'aval_address',
}


class UploadAvalDemographicsView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            nombre = str(fila.get('aval_name') or '').strip()
            rut = str(fila.get('aval_rut') or '').strip()
            dv = str(fila.get('aval_dv') or '').strip()
            email = str(fila.get('aval_email') or '').strip()
            direccion = str(fila.get('aval_address') or '').strip()
            if not nombre:
                errores.append('aval_name: vacío')
            if not rut:
                errores.append('aval_rut: vacío')
            if not dv:
                errores.append('aval_dv: vacío')
            if not email:
                errores.append('aval_email: vacío')
            elif '@' not in email:
                errores.append(f'aval_email: "{email}" no parece un email válido')
            if not direccion:
                errores.append('aval_address: vacía')

            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            idd = None
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')
            else:
                idd = IDDemographics.objects.filter(lead=lead).first()
                if not idd:
                    errores.append(
                        f'el lead OP={fila.get("op")} no tiene demografía principal cargada todavía '
                        '(sube primero el archivo de email/dirección)'
                    )

            if errores:
                return None, errores
            return {'idd': idd, 'lead': lead, 'nombre': nombre, 'rut': rut, 'dv': dv, 'email': email, 'direccion': direccion}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), AVAL_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'aval_name', 'aval_rut', 'aval_dv', 'aval_email', 'aval_address'),
            validar_fila, nombre_archivo='errores_aval.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        leads_tocados = set()
        with transaction.atomic():
            for f in resultado.filas:
                aval, _ = AvalDemographics.objects.get_or_create(id_demographics=f['idd'])
                aval.aval_name = f['nombre']
                aval.aval_rut = f['rut']
                aval.aval_dv = f['dv']
                aval.aval_email = f['email']
                aval.aval_address = f['direccion']
                aval.save()
                leads_tocados.add(f['lead'].pk)
        _recompute_inubicable_bulk(leads_tocados, request.user)

        messages.success(request, f"{len(resultado.filas)} aval(es) cargado(s) correctamente.")
        return redirect('demographics:index')


# =========================================================================================
# Estado de demografía: pantallas para ver/cambiar el estado de teléfonos y correos.
# =========================================================================================

class PhoneStatusView(SupervisorRequiredMixin, View):
    template_name = 'demographics/phone_status.html'

    def get(self, request, *args, **kwargs):
        q = request.GET.get('q', '').strip()
        # Alcance por cartera: un supervisor solo ve/edita los datos de sus carteras.
        phones = scope_por_lead(Phone.objects.select_related('lead__subcartera__cartera'), request.user)
        if q:
            phones = phones.filter(
                Q(phone_number__icontains=q) | Q(lead__op__icontains=q) | Q(lead__name__icontains=q)
            )
        phones = phones.order_by('lead__op', 'phone_number')[:300]
        return render(request, self.template_name, {
            'q': q, 'phones': phones, 'status_choices': CHOICES_CONTACT_STATUS,
        })

    def post(self, request, *args, **kwargs):
        phone = get_object_or_404(Phone, pk=request.POST.get('phone_id'))
        nuevo = _norm_status(request.POST.get('status'))
        if not nuevo:
            messages.error(request, 'Estado inválido.')
        else:
            phone.phone_number_status = nuevo
            phone.whatsapp_activo = request.POST.get('whatsapp_activo') == 'on'
            phone.save(update_fields=['phone_number_status', 'whatsapp_activo'])
            from actions.status_logic import recompute_inubicable
            recompute_inubicable(phone.lead, changed_by=request.user)
            messages.success(request, f'Teléfono {phone.phone_number} actualizado.')
        return redirect(request.POST.get('next') or 'demographics:phone_status')


PHONE_STATUS_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'telefono': 'telefono', 'phone_number': 'telefono', 'numero': 'telefono', 'fono': 'telefono',
    'estado': 'estado', 'status': 'estado', 'phone_status': 'estado',
    'whatsapp': 'whatsapp',
}


class PhoneStatusBulkView(SupervisorRequiredMixin, View):
    """Excel: CARTERA, SUBCARTERA, ID, TELEFONO, ESTADO, WHATSAPP (whatsapp opcional: si/no)."""

    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            numero = str(fila.get('telefono') or '').strip()
            if not numero:
                errores.append('teléfono: vacío')
            nuevo = _norm_status(fila.get('estado'))
            if not nuevo:
                errores.append(f'estado: "{fila.get("estado")}" inválido')

            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            phone = None
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')
            elif numero:
                phone = Phone.objects.filter(lead=lead, phone_number=numero).first()
                if not phone:
                    errores.append(f'el lead OP={fila.get("op")} no tiene el teléfono {numero}')

            whatsapp_raw = fila.get('whatsapp')
            whatsapp = None
            if whatsapp_raw not in (None, ''):
                whatsapp = str(whatsapp_raw).strip().lower() in ('si', 'sí', 'yes', 'true', '1')

            if errores:
                return None, errores
            return {'phone': phone, 'estado': nuevo, 'whatsapp': whatsapp, 'lead': lead}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), PHONE_STATUS_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'telefono', 'estado'), validar_fila,
            nombre_archivo='errores_estado_telefonos.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        from actions.status_logic import recompute_inubicable
        leads_tocados = set()
        with transaction.atomic():
            for f in resultado.filas:
                f['phone'].phone_number_status = f['estado']
                if f['whatsapp'] is not None:
                    f['phone'].whatsapp_activo = f['whatsapp']
                f['phone'].save()
                leads_tocados.add(f['lead'].pk)
        for lead in Lead.objects.filter(pk__in=leads_tocados):
            recompute_inubicable(lead, changed_by=request.user)

        messages.success(request, f"{len(resultado.filas)} teléfono(s) actualizado(s).")
        return redirect('demographics:phone_status')


class EmailStatusView(SupervisorRequiredMixin, View):
    template_name = 'demographics/email_status.html'

    def _emails(self, q):
        items = []
        # Alcance por cartera (supervisor: solo sus carteras).
        idd = scope_por_lead(
            IDDemographics.objects.select_related('lead__subcartera__cartera'), self.request.user
        ).exclude(principal_email='')
        avals = scope_por_lead(
            AvalDemographics.objects.select_related('id_demographics__lead__subcartera__cartera'),
            self.request.user, lead_field='id_demographics__lead',
        ).exclude(aval_email='').exclude(aval_email__isnull=True)
        if q:
            idd = idd.filter(Q(principal_email__icontains=q) | Q(lead__op__icontains=q) | Q(lead__name__icontains=q))
            avals = avals.filter(
                Q(aval_email__icontains=q) | Q(id_demographics__lead__op__icontains=q)
                | Q(id_demographics__lead__name__icontains=q)
            )
        for d in idd[:200]:
            items.append({'kind': 'principal', 'pk': d.pk, 'email': d.principal_email,
                          'status': d.principal_email_status, 'lead': d.lead})
        for a in avals[:200]:
            items.append({'kind': 'aval', 'pk': a.pk, 'email': a.aval_email,
                          'status': a.aval_email_status, 'lead': a.id_demographics.lead})
        items.sort(key=lambda x: (x['lead'].op if x['lead'] else '', x['email']))
        return items

    def get(self, request, *args, **kwargs):
        q = request.GET.get('q', '').strip()
        return render(request, self.template_name, {
            'q': q, 'emails': self._emails(q), 'status_choices': CHOICES_CONTACT_STATUS,
        })

    def post(self, request, *args, **kwargs):
        kind = request.POST.get('kind')
        pk = request.POST.get('pk')
        nuevo = _norm_status(request.POST.get('status'))
        if not nuevo:
            messages.error(request, 'Estado inválido.')
            return redirect(request.POST.get('next') or 'demographics:email_status')
        from actions.status_logic import recompute_inubicable
        if kind == 'principal':
            d = get_object_or_404(IDDemographics, pk=pk)
            d.principal_email_status = nuevo
            d.save(update_fields=['principal_email_status'])
            lead = d.lead
        else:
            a = get_object_or_404(AvalDemographics, pk=pk)
            a.aval_email_status = nuevo
            a.save(update_fields=['aval_email_status'])
            lead = a.id_demographics.lead
        if lead:
            recompute_inubicable(lead, changed_by=request.user)
        messages.success(request, 'Correo actualizado.')
        return redirect(request.POST.get('next') or 'demographics:email_status')


EMAIL_STATUS_UPLOAD_ALIASES = {
    'cartera': 'cartera', 'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'correo': 'correo', 'email': 'correo', 'mail': 'correo',
    'estado': 'estado', 'status': 'estado',
}


class EmailStatusBulkView(SupervisorRequiredMixin, View):
    """Excel: CARTERA, SUBCARTERA, ID, CORREO, ESTADO."""

    def post(self, request, *args, **kwargs):
        from core.bulk_upload import procesar_carga

        def validar_fila(fila, rownum):
            errores = []
            correo = str(fila.get('correo') or '').strip()
            if not correo:
                errores.append('correo: vacío')
            nuevo = _norm_status(fila.get('estado'))
            if not nuevo:
                errores.append(f'estado: "{fila.get("estado")}" inválido')

            lead = find_lead(fila.get('cartera'), fila.get('subcartera'), fila.get('op'))
            if not lead:
                errores.append(f'no se encontró el lead OP={fila.get("op")} en {fila.get("cartera")}/{fila.get("subcartera")}')
            elif correo:
                existe = (
                    IDDemographics.objects.filter(lead=lead, principal_email=correo).exists()
                    or AvalDemographics.objects.filter(id_demographics__lead=lead, aval_email=correo).exists()
                )
                if not existe:
                    errores.append(f'el lead OP={fila.get("op")} no tiene el correo {correo}')

            if errores:
                return None, errores
            return {'lead': lead, 'correo': correo, 'estado': nuevo}, []

        resultado = procesar_carga(
            request.FILES.get('excel_file'), EMAIL_STATUS_UPLOAD_ALIASES,
            ('cartera', 'subcartera', 'op', 'correo', 'estado'), validar_fila,
            nombre_archivo='errores_estado_correos.xlsx',
        )
        if not resultado.ok:
            return resultado.respuesta_error

        from actions.status_logic import recompute_inubicable
        leads_tocados = set()
        actualizados = 0
        with transaction.atomic():
            for f in resultado.filas:
                n = IDDemographics.objects.filter(lead=f['lead'], principal_email=f['correo']).update(principal_email_status=f['estado'])
                n += AvalDemographics.objects.filter(id_demographics__lead=f['lead'], aval_email=f['correo']).update(aval_email_status=f['estado'])
                actualizados += n
                leads_tocados.add(f['lead'].pk)
        for lead in Lead.objects.filter(pk__in=leads_tocados):
            recompute_inubicable(lead, changed_by=request.user)

        messages.success(request, f"{actualizados} correo(s) actualizado(s).")
        return redirect('demographics:email_status')
