import re
import unicodedata
from io import BytesIO

from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from openpyxl import Workbook, load_workbook
from lead.models import Lead
from .models import IDItem, Phone, IDDemographics, AvalDemographics

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
                phone.phone_number_status = phone_status
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
