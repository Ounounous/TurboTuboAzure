import datetime
import zipfile

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum, Count, Max
from django.shortcuts import get_object_or_404, redirect,render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.http import HttpResponse
from django.views import View
from django.utils.dateparse import parse_date
from openpyxl import load_workbook
from .models import Action, Medio, Resultado, PendingPbxCall, CallRecording, PaymentCommitment, Payment
from .pbx_client import PbxClient, PbxError
from lead.models import Lead
from team.models import Team
from cartera.models import Cartera
from demographics.models import Phone
from demographics.views import find_lead, _normalize_header
from .forms import ActionForm, LeadSearchForm, DemographicSelectionForm, PaymentForm
import openpyxl
import re
from io import BytesIO
import logging

logger = logging.getLogger(__name__)


def _period_bounds(today):
    """(hoy_ini, hoy_fin_excl, semana_ini, semana_fin_excl, mes_ini, mes_fin_excl)."""
    week_start, week_end, month_start, next_month = _rango_semana_mes(today)
    return (
        today, today + datetime.timedelta(days=1),
        week_start, week_end + datetime.timedelta(days=1),
        month_start, next_month,
    )


def _by_field_counts(qs, field, start, end_excl):
    rows = (
        qs.filter(created_at__date__gte=start, created_at__date__lt=end_excl)
        .values(field).annotate(n=Count('id'))
    )
    return {(r[field] or '—'): r['n'] for r in rows}


class ActionIndexView(LoginRequiredMixin, View):
    """
    Panel de Gestiones: comparación Día/Semana/Mes por usuario y por resultado, resumen de
    compromisos y pagos, y un listado de gestiones filtrable (con las mismas acciones rápidas
    que la lista de Clientes: ver, gestionar, nota, favorito).
    """

    def get(self, request, *args, **kwargs):
        all_carteras = Cartera.objects.all()

        user_profile = getattr(request.user, 'userprofile', None)
        es_super = bool(user_profile and user_profile.user_type in ('admin', 'owner', 'supervisor'))

        if es_super and user_profile.active_team:
            base_actions = Action.objects.filter(team=user_profile.active_team)
            leads_scope = Lead.objects.filter(team=user_profile.active_team)
            pc_scope = PaymentCommitment.objects.filter(lead__team=user_profile.active_team)
            pay_scope = Payment.objects.filter(lead__team=user_profile.active_team)
        else:
            base_actions = Action.objects.filter(user=request.user)
            leads_scope = Lead.objects.filter(Q(assigned_to=request.user) | Q(created_by=request.user))
            pc_scope = PaymentCommitment.objects.filter(created_by=request.user)
            pay_scope = Payment.objects.filter(created_by=request.user)

        today = timezone.localdate()
        hoy_ini, hoy_fin, sem_ini, sem_fin, mes_ini, mes_fin = _period_bounds(today)

        # ---- Gestiones por usuario (Día/Semana/Mes) ----
        by_user_hoy = _by_field_counts(base_actions, 'user__username', hoy_ini, hoy_fin)
        by_user_sem = _by_field_counts(base_actions, 'user__username', sem_ini, sem_fin)
        by_user_mes = _by_field_counts(base_actions, 'user__username', mes_ini, mes_fin)
        contact_rows = base_actions.filter(created_at__date__gte=mes_ini, created_at__date__lt=mes_fin).values(
            'user__username'
        ).annotate(total=Count('id'), con=Count('id', filter=Q(resultado__contactabilidad='con_contacto')))
        contact_by_user = {
            (r['user__username'] or '—'): (round(100 * r['con'] / r['total']) if r['total'] else 0)
            for r in contact_rows
        }
        usernames = sorted(
            set(by_user_hoy) | set(by_user_sem) | set(by_user_mes),
            key=lambda u: -by_user_mes.get(u, 0),
        )
        usuarios_tabla = [
            {
                'user': u, 'hoy': by_user_hoy.get(u, 0), 'semana': by_user_sem.get(u, 0),
                'mes': by_user_mes.get(u, 0), 'contact': contact_by_user.get(u, 0),
            }
            for u in usernames
        ]

        # ---- Resultados (Día/Semana/Mes) ----
        by_res_hoy = _by_field_counts(base_actions, 'resultado__nombre', hoy_ini, hoy_fin)
        by_res_sem = _by_field_counts(base_actions, 'resultado__nombre', sem_ini, sem_fin)
        by_res_mes = _by_field_counts(base_actions, 'resultado__nombre', mes_ini, mes_fin)
        resultado_names = sorted(
            set(by_res_hoy) | set(by_res_sem) | set(by_res_mes),
            key=lambda r: -by_res_mes.get(r, 0),
        )[:8]
        resultados_tabla = [
            {'resultado': r, 'hoy': by_res_hoy.get(r, 0), 'semana': by_res_sem.get(r, 0), 'mes': by_res_mes.get(r, 0)}
            for r in resultado_names
        ]

        # ---- Compromisos y pagos (Día/Semana/Mes) ----
        compromisos_periodo = {
            'hoy': _resumen(pc_scope.filter(fecha_compromiso=today)),
            'semana': _resumen(pc_scope.filter(fecha_compromiso__gte=sem_ini, fecha_compromiso__lt=sem_fin)),
            'mes': _resumen(pc_scope.filter(fecha_compromiso__gte=mes_ini, fecha_compromiso__lt=mes_fin)),
        }
        pagos_periodo = {
            'hoy': _resumen(pay_scope.filter(fecha=today)),
            'semana': _resumen(pay_scope.filter(fecha__gte=sem_ini, fecha__lt=sem_fin)),
            'mes': _resumen(pay_scope.filter(fecha__gte=mes_ini, fecha__lt=mes_fin)),
        }

        # ---- KPIs (sin "mejor ejecutivo") ----
        gestiones_hoy_total = base_actions.filter(created_at__date=today).count()
        gestiones_hoy_con = base_actions.filter(
            created_at__date=today, resultado__contactabilidad='con_contacto'
        ).count()
        contactabilidad_hoy = round(100 * gestiones_hoy_con / gestiones_hoy_total) if gestiones_hoy_total else 0
        cutoff = today - datetime.timedelta(days=7)
        sin_gestionar = leads_scope.annotate(last_action=Max('actions__created_at')).filter(
            Q(last_action__date__lt=cutoff) | Q(last_action__isnull=True)
        ).count()

        # ---- Listado de gestiones (filtrable, con acciones rápidas por cliente) ----
        f_periodo = request.GET.get('f_periodo', 'hoy')
        if f_periodo not in ('hoy', 'semana', 'mes'):
            f_periodo = 'hoy'
        f_usuario = request.GET.get('f_usuario', '').strip()
        f_resultado = request.GET.get('f_resultado', '').strip()
        f_cartera = request.GET.get('f_cartera', '').strip()
        f_solo_compromiso = request.GET.get('f_solo_compromiso', '') == '1'

        listado = base_actions.select_related('lead__subcartera__cartera', 'medio', 'resultado', 'user')
        if f_periodo == 'semana':
            listado = listado.filter(created_at__date__gte=sem_ini, created_at__date__lt=sem_fin)
        elif f_periodo == 'mes':
            listado = listado.filter(created_at__date__gte=mes_ini, created_at__date__lt=mes_fin)
        else:
            listado = listado.filter(created_at__date=today)
        if f_usuario:
            listado = listado.filter(user__username=f_usuario)
        if f_resultado:
            listado = listado.filter(resultado__nombre=f_resultado)
        if f_cartera:
            listado = listado.filter(subcartera__cartera_id=f_cartera)
        if f_solo_compromiso:
            listado = listado.filter(create_payment_commitment=True)
        listado = list(listado.order_by('-created_at')[:200])

        fav_ids = set(
            Lead.objects.filter(
                favorited_by=request.user, pk__in=[a.lead_id for a in listado]
            ).values_list('pk', flat=True)
        )
        for a in listado:
            a.lead.is_fav = a.lead_id in fav_ids

        return render(
            request,
            'actions/action_index.html',
            {
                'all_teams': Team.objects.all(),
                'all_carteras': all_carteras,
                'usuarios_tabla': usuarios_tabla,
                'resultados_tabla': resultados_tabla,
                'compromisos_periodo': compromisos_periodo,
                'pagos_periodo': pagos_periodo,
                'gestiones_hoy_total': gestiones_hoy_total,
                'contactabilidad_hoy': contactabilidad_hoy,
                'sin_gestionar': sin_gestionar,
                'listado': listado,
                'f_periodo': f_periodo,
                'f_usuario': f_usuario,
                'f_resultado': f_resultado,
                'f_cartera': f_cartera,
                'f_solo_compromiso': f_solo_compromiso,
                'usuarios_choices': usernames,
                'resultados_choices': sorted(set(by_res_hoy) | set(by_res_sem) | set(by_res_mes)),
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
                'lead': lead, 'demographic_form': form, 'step': step,
                'lead_notes': lead.notes.select_related('author'),
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
                'lead_notes': lead.notes.select_related('author'),
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


def _rango_semana_mes(today):
    """Devuelve (inicio_semana, fin_semana, inicio_mes, inicio_mes_siguiente)."""
    week_start = today - datetime.timedelta(days=today.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    month_start = today.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    return week_start, week_end, month_start, next_month


def _resumen(qs, campo_monto='monto'):
    agg = qs.aggregate(n=Count('id'), total=Sum(campo_monto))
    return {'count': agg['n'] or 0, 'total': agg['total'] or 0}


class PaymentCommitmentListView(SupervisorRequiredMixin, View):
    template_name = 'actions/commitments_list.html'

    def get(self, request, *args, **kwargs):
        selected_op = request.GET.get('op', '').strip()
        selected_cartera = request.GET.get('cartera', '').strip()
        selected_fecha = request.GET.get('fecha', '').strip()

        filtered = PaymentCommitment.objects.select_related('lead', 'subcartera__cartera', 'created_by')
        if selected_op:
            filtered = filtered.filter(lead__op__icontains=selected_op)
        if selected_cartera:
            filtered = filtered.filter(subcartera__cartera_id=selected_cartera)
        if selected_fecha:
            parsed = parse_date(selected_fecha)
            if parsed:
                filtered = filtered.filter(fecha_compromiso=parsed)
        filtered = filtered.order_by('-fecha_compromiso', '-created_at')

        # Cada cartera con su propia tabla y su propia suma.
        grupos = {}
        for c in filtered:
            nom = c.subcartera.cartera.nombre if c.subcartera and c.subcartera.cartera else '(sin cartera)'
            g = grupos.setdefault(nom, {'items': [], 'total': 0, 'count': 0})
            g['items'].append(c)
            g['total'] += c.monto or 0
            g['count'] += 1
        grupos_list = [{'cartera': nom, **data} for nom, data in sorted(grupos.items())]
        gran_total = sum(g['total'] for g in grupos_list)
        gran_count = sum(g['count'] for g in grupos_list)

        # Resumen por fecha de compromiso (hoy / esta semana / este mes), sobre todos los compromisos.
        today = timezone.localdate()
        week_start, week_end, month_start, next_month = _rango_semana_mes(today)
        base = PaymentCommitment.objects.all()
        context = {
            'grupos': grupos_list,
            'gran_total': gran_total,
            'gran_count': gran_count,
            'resumen_hoy': _resumen(base.filter(fecha_compromiso=today)),
            'resumen_semana': _resumen(base.filter(fecha_compromiso__gte=week_start, fecha_compromiso__lte=week_end)),
            'resumen_mes': _resumen(base.filter(fecha_compromiso__gte=month_start, fecha_compromiso__lt=next_month)),
            'carteras': Cartera.objects.all(),
            'selected_op': selected_op,
            'selected_cartera': selected_cartera,
            'selected_fecha': selected_fecha,
        }
        return render(request, self.template_name, context)


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


# ------------------ Carga masiva de gestiones (campañas: IVR, SMS, discador, etc.) ------------------

# Encabezados aceptados (normalizados) -> clave interna. Los medios masivos no se gestionan
# uno por uno en el formulario; se cargan en bloque desde el Excel de resultados de la campaña.
BULK_COLUMN_ALIASES = {
    'cartera': 'cartera',
    'subcartera': 'subcartera',
    'op': 'op', 'operacion': 'op', 'id': 'op',
    'medio': 'medio', 'accion': 'medio',
    'resultado': 'resultado', 'estado': 'resultado',
    'sub_estado': 'sub_estado', 'subestado': 'sub_estado', 'tipo_contacto': 'sub_estado',
    'comentario': 'comentario', 'comment': 'comentario', 'observacion': 'comentario',
    'telefono': 'telefono', 'phone': 'telefono', 'fono': 'telefono',
    'email': 'email', 'correo': 'email', 'mail': 'email',
    'fecha_gestion': 'fecha_gestion', 'fecha': 'fecha_gestion',
    'hora_gestion': 'hora_gestion', 'hora': 'hora_gestion',
    'usuario': 'usuario', 'user': 'usuario', 'ejecutivo': 'usuario',
}

BULK_TEMPLATE_HEADERS = [
    'cartera', 'subcartera', 'op', 'medio', 'resultado', 'sub_estado',
    'comentario', 'telefono', 'email', 'fecha_gestion', 'hora_gestion', 'usuario',
]

BULK_TEMPLATE_EXAMPLE = [
    'Nuevo Capital', 'ZONA SUR', 'NC-001', 'IVR', 'CONTACTADO', 'DIRECTO',
    'Campaña IVR 14-07', '56977665544', '', '2026-07-14', '15:30', '',
]


def _bulk_parse_date(value):
    """Acepta datetime/date de openpyxl o texto (YYYY-MM-DD o DD-MM-YYYY / DD/MM/YYYY)."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    parsed = parse_date(text)
    if parsed:
        return parsed
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _bulk_parse_time(value):
    """Acepta time/datetime de openpyxl o texto (HH:MM o HH:MM:SS)."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    text = str(value).strip()
    for fmt in ('%H:%M:%S', '%H:%M', '%H.%M'):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


class BulkActionUploadView(SupervisorRequiredMixin, View):
    """Carga masiva de gestiones desde Excel (una fila = una gestión ya realizada)."""
    template_name = 'actions/bulk_upload.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

    def post(self, request, *args, **kwargs):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'Debes seleccionar un archivo Excel.')
            return redirect('actions:bulk_upload')

        try:
            wb = load_workbook(excel_file, data_only=True)
        except Exception:
            messages.error(request, 'No se pudo leer el archivo. Debe ser un Excel (.xlsx) válido.')
            return redirect('actions:bulk_upload')

        sheet = wb.active
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        colmap = {}
        for idx, raw in enumerate(header_row):
            key = BULK_COLUMN_ALIASES.get(_normalize_header(raw))
            if key and key not in colmap:
                colmap[key] = idx

        faltan = [c for c in ('cartera', 'subcartera', 'op', 'medio', 'resultado') if c not in colmap]
        if faltan:
            messages.error(request, 'Faltan columnas obligatorias en el Excel: ' + ', '.join(faltan) + '.')
            return redirect('actions:bulk_upload')

        def cell(row, key):
            idx = colmap.get(key)
            if idx is None or idx >= len(row):
                return None
            val = row[idx]
            return val

        report_tz = datetime.timezone(datetime.timedelta(hours=-4))
        medios_cache = {}      # cartera_id -> {nombre_upper: Medio}
        resultados_cache = {}  # cartera_id -> {'exact': {(nom,tipo): r}, 'by_name': {nom: [r,...]}}
        user_cache = {}        # username_lower -> User or None

        def get_medios(cartera):
            if cartera.id not in medios_cache:
                medios_cache[cartera.id] = {
                    m.nombre.strip().upper(): m for m in Medio.objects.filter(cartera=cartera)
                }
            return medios_cache[cartera.id]

        def get_resultados(cartera):
            if cartera.id not in resultados_cache:
                exact, by_name = {}, {}
                for r in Resultado.objects.filter(cartera=cartera):
                    nom = r.nombre.strip().upper()
                    exact[(nom, (r.tipo_contacto or '').strip().upper())] = r
                    by_name.setdefault(nom, []).append(r)
                resultados_cache[cartera.id] = {'exact': exact, 'by_name': by_name}
            return resultados_cache[cartera.id]

        def get_user(username):
            key = (username or '').strip().lower()
            if not key:
                return None
            if key not in user_cache:
                user_cache[key] = User.objects.filter(username__iexact=key).first()
            return user_cache[key]

        creadas, errores = 0, []
        for rownum, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not row or all(v in (None, '') for v in row):
                continue

            cartera_nom = cell(row, 'cartera')
            subcartera_nom = cell(row, 'subcartera')
            op = cell(row, 'op')
            medio_nom = cell(row, 'medio')
            resultado_nom = cell(row, 'resultado')

            if not (cartera_nom and subcartera_nom and op and medio_nom and resultado_nom):
                errores.append(f'Fila {rownum}: faltan datos obligatorios (cartera, subcartera, op, medio o resultado).')
                continue

            lead = find_lead(cartera_nom, subcartera_nom, op)
            if not lead:
                errores.append(f'Fila {rownum}: no se encontró el lead OP={op} en {cartera_nom} / {subcartera_nom}.')
                continue

            cartera = lead.subcartera.cartera
            medio = get_medios(cartera).get(str(medio_nom).strip().upper())
            if not medio:
                errores.append(f'Fila {rownum}: la cartera {cartera.nombre} no tiene el medio "{medio_nom}".')
                continue

            res_data = get_resultados(cartera)
            nom_up = str(resultado_nom).strip().upper()
            sub_estado = cell(row, 'sub_estado')
            if sub_estado:
                resultado = res_data['exact'].get((nom_up, str(sub_estado).strip().upper()))
                if not resultado:
                    errores.append(f'Fila {rownum}: no existe el resultado "{resultado_nom}" con sub estado "{sub_estado}" en {cartera.nombre}.')
                    continue
            else:
                candidatos = res_data['by_name'].get(nom_up, [])
                if not candidatos:
                    errores.append(f'Fila {rownum}: la cartera {cartera.nombre} no tiene el resultado "{resultado_nom}".')
                    continue
                if len(candidatos) > 1:
                    errores.append(f'Fila {rownum}: el resultado "{resultado_nom}" es ambiguo en {cartera.nombre}; agrega la columna sub_estado.')
                    continue
                resultado = candidatos[0]

            telefono = cell(row, 'telefono')
            phone_obj = None
            if telefono:
                digits = re.sub(r'\D', '', str(telefono))
                if digits:
                    for p in Phone.objects.filter(lead=lead):
                        if re.sub(r'\D', '', p.phone_number or '') == digits:
                            phone_obj = p
                            break

            email = cell(row, 'email')
            email = str(email).strip() if email else None
            if email and '@' not in email:
                email = None

            action = Action(
                lead=lead,
                medio=medio,
                resultado=resultado,
                user=get_user(cell(row, 'usuario')) or request.user,
                comment=str(cell(row, 'comentario') or ''),
                phone=phone_obj,
                email=email if not phone_obj else None,
            )
            try:
                action.save()
            except Exception as exc:
                errores.append(f'Fila {rownum}: no se pudo guardar ({exc}).')
                continue

            fecha_gestion = _bulk_parse_date(cell(row, 'fecha_gestion'))
            if fecha_gestion:
                # created_at es auto_now_add; para respetar la fecha/hora real de la campaña se
                # sobrescribe con un UPDATE. Si no viene hora, se usa mediodía (UTC-4) para caer
                # en el día correcto del reporte.
                hora = _bulk_parse_time(cell(row, 'hora_gestion')) or datetime.time(12, 0)
                dt = datetime.datetime.combine(fecha_gestion, hora, tzinfo=report_tz)
                Action.objects.filter(pk=action.pk).update(created_at=dt)

            creadas += 1

        if creadas:
            messages.success(request, f'{creadas} gestión(es) cargada(s) correctamente.')
        if errores:
            for e in errores[:100]:
                messages.error(request, e)
            if len(errores) > 100:
                messages.error(request, f'... y {len(errores) - 100} error(es) más.')
        if not creadas and not errores:
            messages.error(request, 'El archivo no tenía filas de datos.')

        return redirect('actions:bulk_upload')


class BulkActionTemplateView(SupervisorRequiredMixin, View):
    """Descarga la plantilla Excel para la carga masiva de gestiones."""

    def get(self, request, *args, **kwargs):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Gestiones'
        ws.append(BULK_TEMPLATE_HEADERS)
        ws.append(BULK_TEMPLATE_EXAMPLE)

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename=plantilla_carga_gestiones.xlsx'
        return response


# ------------------ Pagos (independiente de las gestiones) ------------------

def _es_supervisor(user):
    profile = getattr(user, 'userprofile', None)
    return bool(profile and profile.user_type in ('admin', 'owner', 'supervisor'))


class PaymentCreateView(LoginRequiredMixin, View):
    """Formulario de pago en popup (se abre en el modal, igual que gestiones/notas)."""
    template_name = 'actions/payment_form.html'

    def get(self, request, lead_id, *args, **kwargs):
        lead = get_object_or_404(Lead, id=lead_id)
        form = PaymentForm(initial={'fecha': timezone.localdate()})
        return render(request, self.template_name, {'lead': lead, 'form': form})

    def post(self, request, lead_id, *args, **kwargs):
        lead = get_object_or_404(Lead, id=lead_id)
        form = PaymentForm(request.POST, request.FILES)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.lead = lead
            pago.created_by = request.user
            pago.save()  # subcartera se hereda del lead en Payment.save()
            messages.success(request, 'Pago registrado correctamente.')
            return redirect('actions:popup_close')
        return render(request, self.template_name, {'lead': lead, 'form': form})


class PaymentListView(LoginRequiredMixin, View):
    """Dashboard de pagos: buscador para ingresar un pago, tablas por cartera y sumas del mes."""
    template_name = 'actions/payments_list.html'

    def get(self, request, *args, **kwargs):
        es_super = _es_supervisor(request.user)

        payments = Payment.objects.select_related('lead', 'subcartera__cartera', 'created_by')
        if not es_super:
            payments = payments.filter(Q(lead__assigned_to=request.user) | Q(lead__created_by=request.user))
        payments = payments.order_by('-fecha', '-created_at')

        # Buscador de cliente para registrar un pago.
        q = request.GET.get('q', '').strip()
        lead_results = []
        if q:
            leads = Lead.objects.select_related('subcartera__cartera')
            if not es_super:
                leads = leads.filter(Q(assigned_to=request.user) | Q(created_by=request.user))
            lead_results = list(
                leads.filter(Q(op__icontains=q) | Q(rut__icontains=q) | Q(name__icontains=q))[:20]
            )

        # Todas los pagos agrupados por cartera, cada uno con su suma.
        grupos = {}
        for p in payments:
            nom = p.subcartera.cartera.nombre if p.subcartera and p.subcartera.cartera else '(sin cartera)'
            g = grupos.setdefault(nom, {'items': [], 'total': 0, 'count': 0})
            g['items'].append(p)
            g['total'] += p.monto or 0
            g['count'] += 1
        grupos_list = [{'cartera': nom, **data} for nom, data in sorted(grupos.items())]

        # Sumatoria de pagos de ESTE MES: total y por cartera (N° y monto).
        today = timezone.localdate()
        _, _, month_start, next_month = _rango_semana_mes(today)
        mes_qs = payments.filter(fecha__gte=month_start, fecha__lt=next_month)
        resumen_mes_total = _resumen(mes_qs, 'monto')
        mes_cartera = {}
        for p in mes_qs:
            nom = p.subcartera.cartera.nombre if p.subcartera and p.subcartera.cartera else '(sin cartera)'
            d = mes_cartera.setdefault(nom, {'count': 0, 'total': 0})
            d['count'] += 1
            d['total'] += p.monto or 0
        mes_cartera_list = [{'cartera': nom, **data} for nom, data in sorted(mes_cartera.items())]

        context = {
            'q': q,
            'lead_results': lead_results,
            'grupos': grupos_list,
            'resumen_mes_total': resumen_mes_total,
            'mes_cartera': mes_cartera_list,
        }
        return render(request, self.template_name, context)


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