from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from openpyxl import load_workbook
from lead.models import Lead
from .models import IDItem, Phone, IDDemographics, AvalDemographics


class DemographicsIndexView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        form_type = request.GET.get('form_type', None)
        return render(request, 'demographics/demographics_index.html', {'form_type': form_type})


class UploadIDItemView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        for row in sheet.iter_rows(min_row=2, values_only=True):
            op, cartera, item_type, patente, marca, modelo, año = row[:7]
            lead = Lead.objects.filter(op=op, cartera=cartera).first()
            if lead:
                id_item, created = IDItem.objects.get_or_create(lead=lead)
                id_item.item_type = item_type
                id_item.patente = patente
                id_item.marca = marca
                id_item.modelo = modelo
                id_item.año = año
                id_item.save()
            else:
                print(f"Lead not found for OP: {op}, Cartera: {cartera}")

        return redirect('demographics:index')


class UploadPhoneView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        for row in sheet.iter_rows(min_row=2, values_only=True):
            op, cartera, phone_number, phone_type, phone_status = row[:5]
            lead = Lead.objects.filter(op=op, cartera=cartera).first()
            if lead:
                phone, created = Phone.objects.get_or_create(lead=lead, phone_number=phone_number)
                phone.phone_type = phone_type
                phone.phone_number_status = phone_status
                phone.save()
            else:
                print(f"Lead not found for OP: {op}, Cartera: {cartera}")

        return redirect('demographics:index')


class UploadIDDemographicsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        errors = []
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            op, cartera, principal_email, principal_address = row[:4]

            lead = Lead.objects.filter(op=op, cartera=cartera).first()
            if lead:
                id_demographics, created = IDDemographics.objects.get_or_create(lead=lead)
                id_demographics.principal_email = principal_email
                id_demographics.principal_address = principal_address
                id_demographics.save()
            else:
                error_msg = f"Row {row_number}: Lead not found for OP: {op}, Cartera: {cartera}"
                errors.append(error_msg)
                print(error_msg)

        if errors:
            messages.error(request, "Some leads could not be found.")
            for error in errors:
                messages.error(request, error)

        return redirect('demographics:index')

class UploadAvalDemographicsView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES['excel_file']
        wb = load_workbook(excel_file)
        sheet = wb.active

        errors = []

        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            # Log the entire row data for debugging
            print(f"Processing Row {row_number}: {row}")

            try:
                op, cartera, aval_name, aval_rut, aval_dv, aval_email, aval_address = row[:7]
            except ValueError as e:
                error_msg = f"Row {row_number}: Could not unpack row data correctly - {str(e)}"
                errors.append(error_msg)
                print(error_msg)
                continue

            # Validate field presence
            missing_fields = []
            if not op:
                missing_fields.append('op')
            if not cartera:
                missing_fields.append('cartera')
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
                error_msg = (f"Row {row_number}: Missing necessary information in "
                             f"fields: {', '.join(missing_fields)}. Row data: {row}")
                errors.append(error_msg)
                print(error_msg)
                continue

            lead = Lead.objects.filter(op=op, cartera=cartera).first()
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
                    else:
                        error_msg = f"Row {row_number}: No IDDemographics found for lead with OP: {op}, Cartera: {cartera}"
                        errors.append(error_msg)
                        print(error_msg)
                except IntegrityError as e:
                    error_msg = f"Row {row_number}: Integrity error occurred - {str(e)}"
                    errors.append(error_msg)
                    print(error_msg)
            else:
                error_msg = f"Row {row_number}: Lead not found for OP: {op}, Cartera: {cartera}"
                errors.append(error_msg)
                print(error_msg)

        if errors:
            messages.error(request, "Some errors occurred during the upload.")
            for error in errors:
                messages.error(request, error)

        return redirect('demographics:index')
