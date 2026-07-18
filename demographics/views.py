import re
import unicodedata
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from openpyxl import Workbook, load_workbook
from lead.models import Lead
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


class DownloadTemplateView(LoginRequiredMixin, View):
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


class DemographicsIndexView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        form_type = request.GET.get('form_type', None)
        return render(request, 'demographics/demographics_index.html', {'form_type': form_type})


class UploadIDItemView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        found, not_found = 0, []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, item_type, patente, marca, modelo, año = row[:8]
            lead = find_lead(cartera, subcartera, op)
            if lead:
                id_item, created = IDItem.objects.get_or_create(lead=lead)
                id_item.item_type = item_type
                id_item.patente = patente
                id_item.marca = marca
                id_item.modelo = modelo
                id_item.año = año
                id_item.save()
                found += 1
            else:
                not_found.append(f"Fila {row_number}: no se encontró el lead OP={op} en Cartera={cartera}, Subcartera={subcartera}")

        if found:
            messages.success(request, f"{found} bien(es) cargado(s) correctamente")
        for error in not_found:
            messages.error(request, error)

        return redirect('demographics:index')


class UploadPhoneView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        found, not_found = 0, []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, phone_number, phone_type, phone_status = row[:6]
            lead = find_lead(cartera, subcartera, op)
            if lead:
                phone, created = Phone.objects.get_or_create(lead=lead, phone_number=phone_number)
                phone.phone_type = phone_type
                # Normaliza el estado (acepta español/inglés); si no viene o es inválido, queda activo.
                phone.phone_number_status = _norm_status(phone_status) or Phone.ACTIVE
                phone.save()
                found += 1
            else:
                not_found.append(f"Fila {row_number}: no se encontró el lead OP={op} en Cartera={cartera}, Subcartera={subcartera}")

        if found:
            messages.success(request, f"{found} teléfono(s) cargado(s) correctamente")
        for error in not_found:
            messages.error(request, error)

        return redirect('demographics:index')


class UploadIDDemographicsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        header = [_normalize_header(h) for h in header_row]
        # Busca la columna de email por nombre (acepta 'principal_email', 'email', 'mail',
        # 'correo', etc, sin importar en qué posición venga ni si hay columnas extra como
        # 'tipo'). Si no encuentra ninguna coincidencia, cae de vuelta a la 4ta columna
        # (comportamiento de la plantilla original: cartera, subcartera, op, principal_email).
        email_col = next((i for i, h in enumerate(header) if h in EMAIL_COLUMN_ALIASES), 3)

        found, errors = 0, []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if len(row) < 3:
                continue
            cartera, subcartera, op = row[0], row[1], row[2]
            principal_email = row[email_col] if email_col < len(row) else None

            if principal_email and '@' not in str(principal_email):
                columna = header_row[email_col] if email_col < len(header_row) else email_col
                errors.append(
                    f"Fila {row_number}: '{principal_email}' (columna '{columna}') no parece un correo válido, se omitió."
                )
                continue

            lead = find_lead(cartera, subcartera, op)
            if lead:
                id_demographics, created = IDDemographics.objects.get_or_create(lead=lead)
                id_demographics.principal_email = principal_email
                id_demographics.save()
                found += 1
            else:
                errors.append(f"Fila {row_number}: no se encontró el lead OP={op} en Cartera={cartera}, Subcartera={subcartera}")

        if found:
            messages.success(request, f"{found} email(s) cargado(s) correctamente")
        if errors:
            for error in errors:
                messages.error(request, error)

        return redirect('demographics:index')


class UploadAddressView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        found, errors = 0, []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, principal_address = row[:4]

            lead = find_lead(cartera, subcartera, op)
            if lead:
                id_demographics, created = IDDemographics.objects.get_or_create(lead=lead)
                id_demographics.principal_address = principal_address
                id_demographics.save()
                found += 1
            else:
                errors.append(f"Fila {row_number}: no se encontró el lead OP={op} en Cartera={cartera}, Subcartera={subcartera}")

        if found:
            messages.success(request, f"{found} dirección(es) cargada(s) correctamente")
        if errors:
            for error in errors:
                messages.error(request, error)

        return redirect('demographics:index')


class UploadAvalDemographicsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        found, errors = 0, []

        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            try:
                cartera, subcartera, op, aval_name, aval_rut, aval_dv, aval_email, aval_address = row[:8]
            except ValueError as e:
                errors.append(f"Fila {row_number}: no se pudo leer la fila correctamente - {str(e)}")
                continue

            # Validate field presence
            missing_fields = []
            if not op:
                missing_fields.append('op')
            if not cartera:
                missing_fields.append('cartera')
            if not subcartera:
                missing_fields.append('subcartera')
            if not aval_name:
                missing_fields.append('aval_name')
            if not aval_rut:
                missing_fields.append('aval_rut')
            if aval_dv is None:
                missing_fields.append('aval_dv')
            if not aval_email:
                missing_fields.append('aval_email')
            if not aval_address and aval_address != "sin direccion":
                missing_fields.append('aval_address')

            if missing_fields:
                errors.append(f"Fila {row_number}: faltan campos: {', '.join(missing_fields)}")
                continue

            lead = find_lead(cartera, subcartera, op)
            if lead:
                try:
                    id_demographics = IDDemographics.objects.filter(lead=lead).first()
                    if id_demographics:
                        aval_demographics, created = AvalDemographics.objects.get_or_create(
                            id_demographics=id_demographics)
                        aval_demographics.aval_name = aval_name
                        aval_demographics.aval_rut = aval_rut
                        aval_demographics.aval_dv = aval_dv
                        aval_demographics.aval_email = aval_email
                        aval_demographics.aval_address = aval_address
                        aval_demographics.save()
                        found += 1
                    else:
                        errors.append(f"Fila {row_number}: el lead OP={op} no tiene demografía principal cargada todavía (sube primero el archivo de email/dirección)")
                except IntegrityError as e:
                    errors.append(f"Fila {row_number}: error de integridad - {str(e)}")
            else:
                errors.append(f"Fila {row_number}: no se encontró el lead OP={op} en Cartera={cartera}, Subcartera={subcartera}")

        if found:
            messages.success(request, f"{found} aval(es) cargado(s) correctamente")
        if errors:
            for error in errors:
                messages.error(request, error)

        return redirect('demographics:index')


# =========================================================================================
# Estado de demografía: pantallas para ver/cambiar el estado de teléfonos y correos.
# =========================================================================================

class PhoneStatusView(SupervisorRequiredMixin, View):
    template_name = 'demographics/phone_status.html'

    def get(self, request, *args, **kwargs):
        q = request.GET.get('q', '').strip()
        phones = Phone.objects.select_related('lead__subcartera__cartera')
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


class PhoneStatusBulkView(SupervisorRequiredMixin, View):
    """Excel: CARTERA, SUBCARTERA, ID, TELEFONO, ESTADO, WHATSAPP (whatsapp opcional: si/no)."""

    def post(self, request, *args, **kwargs):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'Debes subir un archivo Excel.')
            return redirect('demographics:phone_status')

        from actions.status_logic import recompute_inubicable
        wb = load_workbook(excel_file)
        sheet = wb.active
        actualizados, errores = 0, []
        leads_tocados = set()
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, phone_number, estado, whatsapp = (list(row) + [None] * 6)[:6]
            if not cartera or not subcartera or not op or not phone_number or not estado:
                errores.append(f"Fila {row_number}: faltan datos (cartera, subcartera, ID, teléfono o estado).")
                continue
            nuevo = _norm_status(estado)
            if not nuevo:
                errores.append(f"Fila {row_number}: estado '{estado}' inválido.")
                continue
            lead = find_lead(cartera, subcartera, op)
            if not lead:
                errores.append(f"Fila {row_number}: no se encontró lead OP={op} en {cartera}/{subcartera}.")
                continue
            phone = Phone.objects.filter(lead=lead, phone_number=str(phone_number).strip()).first()
            if not phone:
                errores.append(f"Fila {row_number}: el lead OP={op} no tiene el teléfono {phone_number}.")
                continue
            phone.phone_number_status = nuevo
            if whatsapp is not None and str(whatsapp).strip() != '':
                phone.whatsapp_activo = str(whatsapp).strip().lower() in ('si', 'sí', 'yes', 'true', '1')
            phone.save()
            leads_tocados.add(lead.pk)
            actualizados += 1

        for lead in Lead.objects.filter(pk__in=leads_tocados):
            recompute_inubicable(lead, changed_by=request.user)
        if actualizados:
            messages.success(request, f'{actualizados} teléfono(s) actualizado(s).')
        for e in errores[:20]:
            messages.error(request, e)
        if len(errores) > 20:
            messages.error(request, f'... y {len(errores) - 20} error(es) más.')
        return redirect('demographics:phone_status')


class EmailStatusView(SupervisorRequiredMixin, View):
    template_name = 'demographics/email_status.html'

    def _emails(self, q):
        items = []
        idd = IDDemographics.objects.select_related('lead__subcartera__cartera').exclude(principal_email='')
        avals = AvalDemographics.objects.select_related('id_demographics__lead__subcartera__cartera').exclude(
            aval_email=''
        ).exclude(aval_email__isnull=True)
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


class EmailStatusBulkView(SupervisorRequiredMixin, View):
    """Excel: CARTERA, SUBCARTERA, ID, CORREO, ESTADO."""

    def post(self, request, *args, **kwargs):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'Debes subir un archivo Excel.')
            return redirect('demographics:email_status')

        from actions.status_logic import recompute_inubicable
        wb = load_workbook(excel_file)
        sheet = wb.active
        actualizados, errores = 0, []
        leads_tocados = set()
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            cartera, subcartera, op, correo, estado = (list(row) + [None] * 5)[:5]
            if not cartera or not subcartera or not op or not correo or not estado:
                errores.append(f"Fila {row_number}: faltan datos (cartera, subcartera, ID, correo o estado).")
                continue
            nuevo = _norm_status(estado)
            if not nuevo:
                errores.append(f"Fila {row_number}: estado '{estado}' inválido.")
                continue
            lead = find_lead(cartera, subcartera, op)
            if not lead:
                errores.append(f"Fila {row_number}: no se encontró lead OP={op} en {cartera}/{subcartera}.")
                continue
            correo = str(correo).strip()
            n = IDDemographics.objects.filter(lead=lead, principal_email=correo).update(principal_email_status=nuevo)
            n += AvalDemographics.objects.filter(id_demographics__lead=lead, aval_email=correo).update(aval_email_status=nuevo)
            if n:
                leads_tocados.add(lead.pk)
                actualizados += n
            else:
                errores.append(f"Fila {row_number}: el lead OP={op} no tiene el correo {correo}.")

        for lead in Lead.objects.filter(pk__in=leads_tocados):
            recompute_inubicable(lead, changed_by=request.user)
        if actualizados:
            messages.success(request, f'{actualizados} correo(s) actualizado(s).')
        for e in errores[:20]:
            messages.error(request, e)
        if len(errores) > 20:
            messages.error(request, f'... y {len(errores) - 20} error(es) más.')
        return redirect('demographics:email_status')
