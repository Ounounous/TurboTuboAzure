import datetime
import zipfile

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect,render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.http import HttpResponse
from django.views import View
from django.utils.dateparse import parse_date
from openpyxl import load_workbook
from .models import Action, Medio, PendingPbxCall, CallRecording, PaymentCommitment
from .pbx_client import PbxClient, PbxError
from lead.models import Lead
from team.models import Team
from cartera.models import Cartera
from demographics.models import AvalDemographics, Phone
from demographics.views import find_lead
from .forms import ActionForm, LeadSearchForm, DemographicSelectionForm, ActionForm
import openpyxl
import re
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


class ActionIndexView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        query = request.GET.get('query', '')

        lead_results = []
        aval_results = []

        if query:
            # Perform a case-insensitive search in the Lead model
            lead_results = Lead.objects.filter(
                Q(id__icontains=query) |
                Q(rut__icontains=query) |
                Q(op__icontains=query)
            )

            # Perform a case-insensitive search in the AvalDemographics model for aval_rut
            aval_results = AvalDemographics.objects.filter(
                Q(aval_rut__icontains=query)
            )

        # Get all teams
        all_teams = Team.objects.all()
        all_carteras = Cartera.objects.all()

        try:
            limit = int(request.GET.get('limit', 10))
        except ValueError:
            limit = 10
        if limit not in (10, 50, 100):
            limit = 10

        # Latest gestiones: supervisors/admins/owners see their team's, collectors see their own
        user_profile = getattr(request.user, 'userprofile', None)
        if user_profile and user_profile.user_type in ('admin', 'owner', 'supervisor'):
            recent_actions = Action.objects.filter(team=user_profile.active_team).select_related(
                'lead', 'medio', 'resultado', 'user'
            )[:limit]
        else:
            recent_actions = Action.objects.filter(user=request.user).select_related(
                'lead', 'medio', 'resultado', 'user'
            )[:limit]

        return render(
            request,
            'actions/action_index.html',
            {
                'lead_results': lead_results,
                'aval_results': aval_results,
                'query': query,
                'all_teams': all_teams,  # Pass all teams to the template
                'all_carteras': all_carteras,
                'recent_actions': recent_actions,
                'limit': limit,
            }
        )

class ActionCreateView(LoginRequiredMixin, CreateView):
    model = Action
    form_class = ActionForm
    template_name = 'actions/action_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['lead'] = self.get_lead()
        return context

    def get_lead(self):
        return get_object_or_404(Lead, pk=self.kwargs['lead_id'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['lead'] = self.get_lead()
        return kwargs

    def get_success_url(self):
        return reverse('leads:detail', kwargs={'pk': self.kwargs['lead_id']})

    def form_valid(self, form):
        form.instance.lead = self.get_lead()
        logger.debug("Form is valid. Saving the action.")
        return super().form_valid(form)

    def form_invalid(self, form):
        # Log form errors for debugging
        logger.debug(f"Form is invalid. Errors: {form.errors}")
        return super().form_invalid(form)


class ActionDetailView(LoginRequiredMixin, DetailView):
    model = Action
    template_name = 'actions/action_detail.html'
    context_object_name = 'action'

class MultiStepActionView(View):
    def get(self, request, step=1, lead_id=None):
        if lead_id:
            lead = get_object_or_404(Lead, id=lead_id)
            request.session['selected_lead_id'] = lead.id
            return redirect('actions:multistep_step', step=2)

        lead_id = request.session.get('selected_lead_id')

        if step == 1:
            form = LeadSearchForm()
            return render(request, 'actions/multistep_form.html', {
                'form': form, 'step': step
            })
        elif step == 2 and lead_id:
            lead = get_object_or_404(Lead, id=lead_id)
            form = DemographicSelectionForm(lead=lead)
            return render(request, 'actions/multistep_form.html', {
                'lead': lead, 'demographic_form': form, 'step': step
            })
        elif step == 3 and lead_id:
            lead = get_object_or_404(Lead, id=lead_id)
            selected_phone_id = request.session.get('selected_phone')
            selected_email = request.session.get('selected_email')
            canal = Medio.CANAL_TELEFONO if selected_phone_id else Medio.CANAL_EMAIL
            selected_phone = Phone.objects.filter(pk=selected_phone_id).first()
            form = ActionForm(cartera=lead.subcartera.cartera, canal=canal)
            userprofile = getattr(request.user, 'userprofile', None)
            return render(request, 'actions/multistep_form.html', {
                'lead': lead, 'action_form': form, 'step': step,
                'canal': canal,
                'selected_phone': selected_phone,
                'phone_digits': re.sub(r'\D', '', selected_phone.phone_number) if selected_phone else '',
                'selected_email': selected_email,
                'has_pbx': bool(userprofile and userprofile.has_pbx_credentials),
            })
        else:
            return redirect('actions:multistep_step', step=1)

    def post(self, request, step):
        lead_id = request.session.get('selected_lead_id')
        lead = get_object_or_404(Lead, id=lead_id)
        if step == 2:
            form = DemographicSelectionForm(request.POST, lead=lead)
            if form.is_valid():
                selected_phone = form.cleaned_data['phone']
                selected_email = form.cleaned_data['email']
                request.session['selected_phone'] = selected_phone.id if selected_phone else None
                request.session['selected_email'] = selected_email
                return redirect('actions:multistep_step', step=3)
            return render(request, 'actions/multistep_form.html', {
                'lead': lead, 'demographic_form': form, 'step': step
            })
        elif step == 3:
            selected_phone_id = request.session.get('selected_phone')
            selected_email = request.session.get('selected_email')
            canal = Medio.CANAL_TELEFONO if selected_phone_id else Medio.CANAL_EMAIL

            form = ActionForm(request.POST, cartera=lead.subcartera.cartera, canal=canal)

            if form.is_valid():
                action = form.save(commit=False)
                action.lead = lead
                action.user = request.user  # Ensure the user is set

                # Ensure previously collected data is set
                action.phone_id = selected_phone_id  # ForeignKey to Phone model
                action.email = selected_email if not selected_phone_id else None  # Only save email if phone is not selected
                action.save()

                if selected_phone_id and action.medio.es_llamada:
                    pending_call = PendingPbxCall.objects.filter(
                        user=request.user, lead=lead, phone_id=selected_phone_id, resolved=False,
                    ).order_by('-requested_at').first()
                    if pending_call:
                        pending_call.action = action
                        pending_call.save(update_fields=['action'])

                logger.debug(f"Action saved: {action}, Lead: {lead}, User: {request.user}")
                messages.success(request, 'Gestión guardada correctamente.')

                if request.POST.get('submit_action') == 'add_another':
                    # Keep the lead selected, forget the phone/email so the user picks again
                    request.session.pop('selected_phone', None)
                    request.session.pop('selected_email', None)
                    return redirect('actions:multistep_step', step=2)

                request.session.pop('selected_lead_id', None)
                request.session.pop('selected_phone', None)
                request.session.pop('selected_email', None)

                return redirect('actions:popup_close')
            else:
                logger.debug(f"Invalid form data: {form.errors}")

            selected_phone = Phone.objects.filter(pk=selected_phone_id).first()
            return render(request, 'actions/multistep_form.html', {
                'lead': lead,
                'action_form': form,
                'step': step,
                'canal': canal,
                'selected_phone': selected_phone,
                'phone_digits': re.sub(r'\D', '', selected_phone.phone_number) if selected_phone else '',
                'selected_email': selected_email,
            })

        return redirect('actions:multistep_step', step=1)


class CancelActionView(LoginRequiredMixin, View):
    def get(self, request, lead_id, *args, **kwargs):
        for key in ('selected_lead_id', 'selected_phone', 'selected_email'):
            request.session.pop(key, None)
        return redirect('actions:popup_close')


class PopupCloseView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return render(request, 'actions/popup_close.html')


class OriginatePbxCallView(LoginRequiredMixin, View):
    """Originates a real call through pbxip.cl using the current user's own credentials."""

    def post(self, request, *args, **kwargs):
        userprofile = getattr(request.user, 'userprofile', None)
        if not userprofile or not userprofile.has_pbx_credentials:
            return JsonResponse({'ok': False, 'reason': 'no_credentials'}, status=400)

        lead_id = request.POST.get('lead_id')
        phone_id = request.POST.get('phone_id')
        lead = get_object_or_404(Lead, pk=lead_id)
        phone = get_object_or_404(Phone, pk=phone_id, lead=lead)
        destination = re.sub(r'\D', '', phone.phone_number)

        if not destination:
            return JsonResponse({'ok': False, 'reason': 'invalid_number'}, status=400)

        client = PbxClient(userprofile.pbx_email, userprofile.pbx_password)
        try:
            client.originate_call(userprofile.pbx_extension, destination)
        except PbxError as exc:
            logger.error(f"PBX originate_call failed for user {request.user.id}: {exc}")
            return JsonResponse({'ok': False, 'reason': 'pbx_error', 'detail': str(exc)}, status=502)

        PendingPbxCall.objects.create(
            user=request.user, lead=lead, phone=phone, destination=destination,
        )

        return JsonResponse({'ok': True})

class ActionDownloadExcelView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        scope = kwargs.get('scope', 'team')

        logger.debug(f"Scope: {scope}, User: {request.user}")

        # Team ID from GET request
        team_id = request.GET.get('team_id')  # Query parameter to select the team

        # Fetch the team if 'scope' is 'team'
        if scope == 'team':
            if not team_id:  # Handle missing team_id
                return JsonResponse(
                    {"error": "No team selected. Please provide a valid team ID to download actions."},
                    status=400
                )

            try:
                # Locate the team by ID
                team = Team.objects.get(id=team_id)
                logger.debug(f"Selected team: {team} (ID: {team_id})")
            except Team.DoesNotExist:
                logger.error(f"Team with ID {team_id} does not exist.")
                return JsonResponse(
                    {"error": f"Team with ID {team_id} does not exist."},
                    status=404
                )

        # Handle user-specific download request (if scope == 'user')
        if scope == 'user':
            logger.debug("Downloading actions for user scope.")

        # Optional cartera filter (each cartera can pull its own report)
        cartera_id = request.GET.get('cartera')

        # Parse optional date range from GET request
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        try:
            if start_date:
                start_date = parse_date(start_date)
            if end_date:
                end_date = parse_date(end_date)
        except ValueError:
            return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)

        # Validate the start-end date range
        if start_date and end_date and start_date > end_date:
            return JsonResponse({"error": "Start date cannot be later than end date."}, status=400)

        # Fetch actions based on the scope
        if scope == 'team':
            actions = Action.objects.filter(team=team)
        elif scope == 'user':
            actions = Action.objects.filter(user=request.user)
        else:
            return JsonResponse({"error": "Invalid scope provided. Allowed scopes: 'team', 'user'."}, status=400)

        # Apply additional filters (by created_at date, and by cartera)
        if start_date:
            actions = actions.filter(created_at__gte=start_date)
        if end_date:
            actions = actions.filter(created_at__lte=end_date)
        if cartera_id:
            actions = actions.filter(subcartera__cartera_id=cartera_id)

        logger.debug(f"{actions.count()} actions found for {scope}")

        # Handle case when no actions are found
        if not actions.exists():
            return JsonResponse({"error": "No actions found for the given criteria."}, status=404)

        # Generate Excel file for download
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = f'{scope.capitalize()} Actions'

        # Add headers to the spreadsheet
        headers = ['OP', 'RUT', 'ACCION', 'SUBESTADO', 'ESTADO', 'FECHA', 'COMENTARIO', 'TELEFONO', 'EMAIL',
                   'USER']
        sheet.append(headers)

        report_tz = datetime.timezone(datetime.timedelta(hours=-4))  # UTC-4, como pide el formato Galgo

        # Insert action data into the Excel sheet
        for action in actions:
            phone = str(action.phone) if action.phone else ''
            email = str(action.email) if action.email else ''
            rut = f"{action.lead.rut}{action.lead.dv}" if action.lead else ''

            sheet.append([
                action.lead.op if action.lead else '',  # OP
                rut,  # RUT (rut + dv concatenados)
                action.medio.nombre,  # ACCION
                action.get_target_display() or '',  # SUBESTADO
                action.resultado.nombre,  # ESTADO
                action.created_at.astimezone(report_tz).strftime("%Y-%m-%d %H:%M:%S"),  # FECHA (UTC-4)
                action.comment if action.comment else '',  # COMENTARIO
                phone,  # TELEFONO
                email,  # EMAIL
                action.user.username if action.user else ''  # USER
            ])

        # Save the workbook to a BytesIO object
        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        # Create HTTP response for downloading the Excel file
        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        filename_parts = [scope, 'actions']
        if cartera_id:
            cartera_obj = Cartera.objects.filter(pk=cartera_id).first()
            if cartera_obj:
                filename_parts.append(re.sub(r'\W+', '_', cartera_obj.nombre))
        response['Content-Disposition'] = f'attachment; filename={"_".join(filename_parts)}.xlsx'
        return response


SUPERVISOR_TYPES = ('admin', 'owner', 'supervisor')


class SupervisorRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        userprofile = getattr(request.user, 'userprofile', None)
        if not userprofile or userprofile.user_type not in SUPERVISOR_TYPES:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class RecordingListView(SupervisorRequiredMixin, ListView):
    model = CallRecording
    template_name = 'actions/recordings_list.html'
    context_object_name = 'recordings'

    def get_limit(self):
        try:
            limit = int(self.request.GET.get('limit', 50))
        except ValueError:
            limit = 50
        return limit if limit in (10, 50, 100) else 50

    def get_queryset(self):
        qs = CallRecording.objects.select_related('lead__subcartera__cartera', 'user').order_by('-created_at')

        op = self.request.GET.get('op')
        if op:
            qs = qs.filter(lead__op__icontains=op)

        cartera_id = self.request.GET.get('cartera')
        if cartera_id:
            qs = qs.filter(lead__subcartera__cartera_id=cartera_id)

        fecha = self.request.GET.get('fecha')
        if fecha:
            parsed = parse_date(fecha)
            if parsed:
                qs = qs.filter(Q(call_date__date=parsed) | Q(call_date__isnull=True, created_at__date=parsed))

        return qs[:self.get_limit()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['limit'] = self.get_limit()
        context['carteras'] = Cartera.objects.all()
        context['selected_op'] = self.request.GET.get('op', '')
        context['selected_cartera'] = self.request.GET.get('cartera', '')
        context['selected_fecha'] = self.request.GET.get('fecha', '')
        return context


class RecordingsExportZipView(SupervisorRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'Debes subir un archivo Excel.')
            return redirect('actions:recordings_list')

        wb = load_workbook(excel_file)
        sheet = wb.active

        buffer = BytesIO()
        errors = []
        found_any = False

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            used_names = set()
            for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                cartera, subcartera, op, fecha = (list(row) + [None] * 4)[:4]
                if not cartera or not subcartera or not op:
                    errors.append(f"Fila {row_number}: faltan cartera, subcartera u OP.")
                    continue

                lead = find_lead(cartera, subcartera, op)
                if not lead:
                    errors.append(f"Fila {row_number}: no se encontró lead OP={op} en Cartera={cartera}, Subcartera={subcartera}.")
                    continue

                recordings = CallRecording.objects.filter(lead=lead)

                if fecha:
                    parsed_date = None
                    if isinstance(fecha, (datetime.date, datetime.datetime)):
                        parsed_date = fecha.date() if isinstance(fecha, datetime.datetime) else fecha
                    else:
                        parsed_date = parse_date(str(fecha).strip())
                    if parsed_date:
                        recordings = recordings.filter(
                            Q(call_date__date=parsed_date) | Q(call_date__isnull=True, created_at__date=parsed_date)
                        )
                    else:
                        errors.append(f"Fila {row_number}: no se pudo interpretar la fecha '{fecha}', se ignoró el filtro.")

                for recording in recordings:
                    if not recording.audio_file:
                        continue
                    name = recording.audio_file.name.rsplit('/', 1)[-1]
                    while name in used_names:
                        name = f"dup_{name}"
                    used_names.add(name)
                    recording.audio_file.open('rb')
                    zf.writestr(name, recording.audio_file.read())
                    recording.audio_file.close()
                    found_any = True

            if errors:
                zf.writestr('errores.txt', '\n'.join(errors))

        if not found_any:
            messages.error(request, 'No se encontraron grabaciones para las filas del Excel subido.')
            for error in errors:
                messages.error(request, error)
            return redirect('actions:recordings_list')

        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename=grabaciones.zip'
        return response


TANNER_GESTOR_CODIGO = '40'  # ZONASUR, tabla de gestores del instructivo Tanner
TANNER_TIPO_GESTION_DEFAULT = '1'  # Cobranza
TANNER_ORIGEN_GESTION_DEFAULT = '2'  # Outbound


def _format_tanner_phone(raw_number):
    digits = re.sub(r'\D', '', raw_number or '')
    if not digits:
        return ''
    if digits.startswith('56'):
        return digits
    if len(digits) == 9:
        return '56' + digits
    return digits


class TannerReportView(LoginRequiredMixin, View):
    """
    Genera el archivo de gestiones para Tanner tal como lo exige su instructivo:
    14 columnas separadas por '|', sin encabezado, un solo dia por archivo, formato
    FechaGestiones_BaseGestiones2_40.txt. Se envia manualmente por correo a
    gestionescobranza@tanner.cl (no se automatiza el envio, solo se genera el archivo).
    """

    def get(self, request, *args, **kwargs):
        fecha_str = request.GET.get('fecha')
        if not fecha_str:
            return JsonResponse({'error': 'Debes indicar una fecha (YYYY-MM-DD).'}, status=400)

        fecha = parse_date(fecha_str)
        if not fecha:
            return JsonResponse({'error': 'Fecha inválida. Usa el formato YYYY-MM-DD.'}, status=400)

        report_tz = datetime.timezone(datetime.timedelta(hours=-4))
        start = datetime.datetime.combine(fecha, datetime.time.min, tzinfo=report_tz)
        end = datetime.datetime.combine(fecha, datetime.time.max, tzinfo=report_tz)

        actions = Action.objects.filter(
            subcartera__cartera__nombre__iexact='Tanner',
            created_at__gte=start,
            created_at__lte=end,
        ).select_related('lead', 'medio', 'resultado', 'user__userprofile', 'phone')

        if not actions.exists():
            return JsonResponse({'error': 'No hay gestiones de Tanner para esa fecha.'}, status=404)

        lines = []
        for action in actions:
            lead = action.lead
            rut_cliente = f"{lead.rut}{lead.dv}"
            compromiso = action.fecha_compromiso.strftime('%d-%m-%Y') if action.fecha_compromiso else ''
            observacion = (action.comment or '').replace('|', ' ').replace('\n', ' ')[:255]
            local_dt = action.created_at.astimezone(report_tz)
            ejecutivo_rut = ''
            if action.user and hasattr(action.user, 'userprofile'):
                ejecutivo_rut = action.user.userprofile.rut

            row = [
                lead.op,
                rut_cliente,
                TANNER_GESTOR_CODIGO,
                compromiso,
                action.resultado.codigo,
                observacion,
                action.medio.codigo,
                local_dt.strftime('%d-%m-%Y'),
                local_dt.strftime('%H:%M:%S'),
                ejecutivo_rut or '99999999',
                _format_tanner_phone(action.phone.phone_number) if action.phone else '',
                action.email or '',
                TANNER_TIPO_GESTION_DEFAULT,
                TANNER_ORIGEN_GESTION_DEFAULT,
            ]
            lines.append('|'.join(str(value) for value in row))

        content = '\r\n'.join(lines) + '\r\n'
        filename = f"{fecha.strftime('%Y%m%d')}_BaseGestiones2_{TANNER_GESTOR_CODIGO}.txt"

        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response


class PaymentCommitmentListView(SupervisorRequiredMixin, ListView):
    model = PaymentCommitment
    template_name = 'actions/commitments_list.html'
    context_object_name = 'commitments'

    def get_limit(self):
        try:
            limit = int(self.request.GET.get('limit', 50))
        except ValueError:
            limit = 50
        return limit if limit in (10, 50, 100) else 50

    def get_queryset(self):
        qs = PaymentCommitment.objects.select_related(
            'lead__subcartera__cartera', 'created_by'
        ).order_by('-fecha_compromiso', '-created_at')

        op = self.request.GET.get('op')
        if op:
            qs = qs.filter(lead__op__icontains=op)

        cartera_id = self.request.GET.get('cartera')
        if cartera_id:
            qs = qs.filter(subcartera__cartera_id=cartera_id)

        fecha = self.request.GET.get('fecha')
        if fecha:
            parsed = parse_date(fecha)
            if parsed:
                qs = qs.filter(fecha_compromiso=parsed)

        return qs[:self.get_limit()]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['limit'] = self.get_limit()
        context['carteras'] = Cartera.objects.all()
        context['selected_op'] = self.request.GET.get('op', '')
        context['selected_cartera'] = self.request.GET.get('cartera', '')
        context['selected_fecha'] = self.request.GET.get('fecha', '')
        return context


class PaymentCommitmentExportExcelView(SupervisorRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        qs = PaymentCommitment.objects.select_related(
            'lead', 'subcartera__cartera', 'created_by'
        ).order_by('-fecha_compromiso', '-created_at')

        op = request.GET.get('op')
        if op:
            qs = qs.filter(lead__op__icontains=op)

        cartera_id = request.GET.get('cartera')
        if cartera_id:
            qs = qs.filter(subcartera__cartera_id=cartera_id)

        fecha = request.GET.get('fecha')
        if fecha:
            parsed = parse_date(fecha)
            if parsed:
                qs = qs.filter(fecha_compromiso=parsed)

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'Compromisos de pago'
        sheet.append(['Cartera', 'Subcartera', 'ID', 'Cliente', 'Fecha compromiso', 'Monto', 'Comentario', 'Ejecutivo'])

        for c in qs:
            sheet.append([
                c.subcartera.cartera.nombre,
                c.subcartera.nombre,
                c.lead.op,
                c.lead.name,
                c.fecha_compromiso.strftime('%d-%m-%Y') if c.fecha_compromiso else '',
                float(c.monto) if c.monto is not None else '',
                c.comentario or '',
                c.created_by.username if c.created_by else '',
            ])

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename=compromisos_de_pago.xlsx'
        return response


NC_EXTERNO = 'ZONA SUR'  # columna "Externo" fija en el reporte de Nuevo Capital


def _ejecutivo_nombre(user):
    if not user:
        return ''
    full = user.get_full_name().strip()
    return (full or user.username).upper()


class NuevoCapitalReportView(LoginRequiredMixin, View):
    """
    Genera el reporte de gestiones de Nuevo Capital (.xlsx, 16 columnas) para un dia.
    Formato de las columnas segun su instructivo (Reporte Salida NC):
    Operacion, RUT, Dv, FechaGest, HoraGest, Usuario, Accion, Sub Estado, Estado,
    Comentario, Fecha Compromiso, Monto Compromiso, Telefono, eMail, Origen Gestion(In=1/Out=2),
    Externo(ZONA SUR).
    """

    HEADERS = [
        'Operación', 'RUT', 'Dv', 'FechaGest', 'Hora Gest', 'Usuario', 'Accion',
        'Sub Estado', 'Estado', 'Comentario', 'Fecha Compromiso', 'Monto Compromiso',
        'Telefono', 'eMail', 'Origen Gestión', 'Externo',
    ]

    def get(self, request, *args, **kwargs):
        fecha_str = request.GET.get('fecha')
        if not fecha_str:
            return JsonResponse({'error': 'Debes indicar una fecha (YYYY-MM-DD).'}, status=400)
        fecha = parse_date(fecha_str)
        if not fecha:
            return JsonResponse({'error': 'Fecha inválida. Usa el formato YYYY-MM-DD.'}, status=400)

        report_tz = datetime.timezone(datetime.timedelta(hours=-4))
        start = datetime.datetime.combine(fecha, datetime.time.min, tzinfo=report_tz)
        end = datetime.datetime.combine(fecha, datetime.time.max, tzinfo=report_tz)

        actions = Action.objects.filter(
            subcartera__cartera__nombre__iexact='Nuevo Capital',
            created_at__gte=start,
            created_at__lte=end,
        ).select_related('lead', 'medio', 'resultado', 'user', 'phone')

        if not actions.exists():
            return JsonResponse({'error': 'No hay gestiones de Nuevo Capital para esa fecha.'}, status=404)

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'Reporte Salida NC'
        sheet.append(self.HEADERS)

        for action in actions:
            lead = action.lead
            local_dt = action.created_at.astimezone(report_tz)
            origen = '1' if action.medio.es_inbound else '2'  # In=1 / Out=2
            sub_estado = action.resultado.tipo_contacto or ''
            compromiso = action.fecha_compromiso.strftime('%d-%m-%Y') if action.fecha_compromiso else ''

            sheet.append([
                lead.op,
                lead.rut,
                lead.dv,
                local_dt.strftime('%d-%m-%Y'),
                local_dt.strftime('%H:%M:%S'),
                _ejecutivo_nombre(action.user),
                action.medio.nombre,
                sub_estado,
                action.resultado.nombre,
                action.comment or '',
                compromiso,
                action.monto_compromiso if action.monto_compromiso else '',
                _format_tanner_phone(action.phone.phone_number) if action.phone else '',
                action.email or '',
                origen,
                NC_EXTERNO,
            ])

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        filename = f"Reporte_Gestiones_NuevoCapital_{fecha.strftime('%Y%m%d')}.xlsx"
        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response