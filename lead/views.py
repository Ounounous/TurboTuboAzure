from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.http import HttpResponse, JsonResponse
from django.views.generic import ListView, DetailView, DeleteView, UpdateView, CreateView, View
from django.utils.timezone import now, localtime, localdate
from .models import StatusChangeLog, Team
import openpyxl
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

from openpyxl import load_workbook

from .forms import AddCommentForm, AddFileForm, AddLeadForm, UploadExcelFileForm, AssignLeadsForm, UploadAssignmentFileForm
from .models import Lead, LeadAssignment, LeadNote, User
from cartera.models import Cartera, Subcartera
from demographics.models import IDDemographics, AvalDemographics, IDItem, Phone


class LeadListView(LoginRequiredMixin, ListView):
    model = Lead

    # Filtros por columna (además del buscador general por ID/RUT). Nombre del parámetro GET ->
    # lookup en el queryset. Pensado para ser expandible: agregar una columna es una línea acá.
    COLUMN_FILTERS = {
        'op': 'op__icontains',
        'name': 'name__icontains',
        'rut': 'rut__icontains',
        'status': 'status',
        'ciclo': 'ciclo',
        'ciclo_cartera': 'ciclo_cartera',
        'activo': 'activo',
        'tipo_cobranza': 'tipo_cobranza',
        'tiene_aval': 'tiene_aval',
        'cartera': 'subcartera__cartera__nombre__icontains',
        'subcartera': 'subcartera__nombre__icontains',
    }

    # Columnas ordenables: clave del parámetro ?sort= -> campo del modelo.
    SORT_FIELDS = {
        'op': 'op', 'nombre': 'name', 'rut': 'rut',
        'insoluto': 'saldo_insoluto', 'deuda': 'saldo_deuda', 'cuota': 'valor_cuota',
        'atrasadas': 'cuotas_atrasadas', 'status': 'status',
        'cartera': 'subcartera__cartera__nombre', 'dias': 'last_action_at',
    }

    def get_limit(self):
        try:
            limit = int(self.request.GET.get('limit', 10))
        except ValueError:
            limit = 10
        return limit if limit in (10, 50, 100) else 10

    def _base_scope(self):
        """Leads visibles para el usuario (asignados o creados por él)."""
        return Lead.objects.filter(
            Q(assigned_to__pk=self.request.user.pk) | Q(created_by=self.request.user)
        )

    def get_queryset(self):
        queryset = self._base_scope().select_related('subcartera__cartera').annotate(
            # Última gestión (Action) del lead — NO cuenta las notas (LeadNote es otro modelo).
            last_action_at=Max('actions__created_at')
        )

        # Solo favoritos del usuario.
        if self.request.GET.get('fav') == '1':
            queryset = queryset.filter(favorited_by=self.request.user)

        # Buscador general: ID (op), nombre y RUT en un solo campo.
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(
                Q(op__icontains=q) | Q(name__icontains=q) | Q(rut__icontains=q)
            )

        # Filtros por columna (panel avanzado, expandible).
        for param, lookup in self.COLUMN_FILTERS.items():
            value = self.request.GET.get(param, '').strip()
            if value:
                queryset = queryset.filter(**{lookup: value})

        return self._apply_sort(queryset)

    def _apply_sort(self, queryset):
        sort = self.request.GET.get('sort', 'nombre')
        direction = self.request.GET.get('dir', 'asc')
        if sort not in self.SORT_FIELDS:
            sort = 'nombre'
        if sort == 'dias':
            # "días desde gestión" = inverso de last_action_at (más antiguo = más días).
            # asc (menos días primero) => last_action_at desc; nunca gestionado (null) al final.
            campo = F('last_action_at')
            order = campo.desc(nulls_last=True) if direction == 'asc' else campo.asc(nulls_last=True)
            return queryset.order_by(order, 'name')
        field = self.SORT_FIELDS[sort]
        return queryset.order_by(field if direction == 'asc' else '-' + field, 'name')

    def _url_with(self, **changes):
        """URL de la misma vista cambiando algunos parámetros (None = quitar)."""
        params = self.request.GET.copy()
        for key, value in changes.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        encoded = params.urlencode()
        return ('?' + encoded) if encoded else '?'

    def _sort_links(self):
        cur_sort = self.request.GET.get('sort', 'nombre')
        cur_dir = self.request.GET.get('dir', 'asc')
        links = {}
        for key in self.SORT_FIELDS:
            new_dir = 'desc' if (cur_sort == key and cur_dir == 'asc') else 'asc'
            arrow = ('▲' if cur_dir == 'asc' else '▼') if cur_sort == key else ''
            links[key] = {'url': self._url_with(sort=key, dir=new_dir), 'arrow': arrow}
        return links

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        limit = self.get_limit()
        base_qs = self.get_queryset()
        context['total_count'] = base_qs.count()

        # ids favoritos del usuario (para pintar la estrella) sobre la página mostrada.
        leads = list(base_qs[:limit])
        fav_ids = set(
            self._base_scope().filter(favorited_by=self.request.user, pk__in=[l.pk for l in leads])
            .values_list('pk', flat=True)
        )
        today = localdate()
        for lead in leads:
            lead.is_fav = lead.pk in fav_ids
            if lead.last_action_at:
                lead.dias_ultima_gestion = (today - localtime(lead.last_action_at).date()).days
            else:
                lead.dias_ultima_gestion = None
        context['leads'] = leads
        context['limit'] = limit

        # Conteos por status (chips) sobre el scope del usuario, sin aplicar el filtro de status.
        scope = self._base_scope()
        status_counts = {row['status']: row['n'] for row in scope.values('status').annotate(n=Count('id'))}
        selected_status = self.request.GET.get('status', '')
        context['status_chips'] = [
            {'value': val, 'label': label, 'count': status_counts.get(val, 0),
             'color': Lead.STATUS_COLOR.get(val, 'slate'),
             'url': self._url_with(status=val), 'active': selected_status == val}
            for val, label in Lead.CHOICES_STATUS
        ]
        context['total_scope'] = scope.count()
        context['fav_count'] = scope.filter(favorited_by=self.request.user).count()
        context['url_todos'] = self._url_with(status=None, fav=None)
        context['url_fav'] = self._url_with(fav='1', status=None)
        context['url_clear_fav'] = self._url_with(fav=None)
        context['sort_links'] = self._sort_links()
        context['url_limit_10'] = self._url_with(limit=10)
        context['url_limit_50'] = self._url_with(limit=50)
        context['url_limit_100'] = self._url_with(limit=100)

        # Estado de filtros/orden para la UI.
        context['q'] = self.request.GET.get('q', '')
        context['selected_status'] = selected_status
        context['only_fav'] = self.request.GET.get('fav') == '1'
        context['sort'] = self.request.GET.get('sort', 'nombre')
        context['dir'] = self.request.GET.get('dir', 'asc')
        active_filters = {p: self.request.GET.get(p, '') for p in self.COLUMN_FILTERS}
        context['filters'] = active_filters
        context['advanced_open'] = any(v for k, v in active_filters.items() if k != 'status')

        context['status_choices'] = Lead.CHOICES_STATUS
        context['ciclo_choices'] = Lead.CHOICES_CICLO
        context['ciclo_cartera_choices'] = Lead.CHOICES_CICLO_CARTERA
        context['activo_choices'] = Lead.CHOICES_ACTIVO
        context['tipo_cobranza_choices'] = Lead.CHOICES_TIPO_COBRANZA
        context['aval_choices'] = Lead.CHOICES_AVAL
        return context

class LeadDetailView(LoginRequiredMixin, DetailView):
    model = Lead

    def get_queryset(self):
        queryset = super().get_queryset()
        # Include leads created by or assigned to the current user
        return queryset.filter(
            Q(created_by=self.request.user) | Q(assigned_to=self.request.user),
            pk=self.kwargs.get('pk')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['demographics'] = IDDemographics.objects.filter(lead=self.object)
        context['aval_demographics'] = AvalDemographics.objects.filter(
            id_demographics__in=context['demographics']).first()
        context['form'] = AddCommentForm()
        context['fileform'] = AddFileForm()
        context['notes'] = self.object.notes.select_related('author')
        context['phones'] = self.object.phone_set.all()

        # Días desde la última gestión (no cuenta notas), igual que en la lista de clientes.
        last_action = self.object.actions.order_by('-created_at').first()
        if last_action:
            context['dias_ultima_gestion'] = (localdate() - localtime(last_action.created_at).date()).days
        else:
            context['dias_ultima_gestion'] = None

        # Próximo compromiso de pago (el más cercano hacia adelante; si no hay futuro, el último).
        today = localdate()
        next_commitment = self.object.payment_commitments.filter(fecha_compromiso__gte=today).order_by('fecha_compromiso').first()
        context['next_commitment'] = next_commitment or self.object.payment_commitments.order_by('-fecha_compromiso').first()

        # Iniciales para el avatar de la ficha.
        parts = self.object.name.split()
        context['initials'] = ((parts[0][0] if parts else '?') + (parts[1][0] if len(parts) > 1 else '')).upper()

        return context
class LeadDeleteView(LoginRequiredMixin, DeleteView):
    model = Lead
    success_url = reverse_lazy('leads:list')
   
    def get_queryset(self):
        queryset = super(LeadDeleteView, self).get_queryset()

        return queryset.filter(created_by=self.request.user, pk=self.kwargs.get('pk'))
    
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)

class LeadUpdateView(LoginRequiredMixin, UpdateView):
    model = Lead
    fields = ('status',)  # Only allow editing of the 'status' field
    success_url = reverse_lazy('leads:list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit Status'  # Update the title for clarity
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        user_profile = self.request.user.userprofile

        # Check if the user is an admin or a supervisor
        if user_profile.user_type in ['admin', 'supervisor']:
            return queryset  # Allow access to all leads for admins and supervisors

        # For other users (e.g., collectors), filter by the assigned lead
        return queryset.filter(assigned_to=self.request.user, pk=self.kwargs.get('pk'))

    def form_valid(self, form):
        response = super().form_valid(form)
        # Log the status change
        StatusChangeLog.objects.create(
            lead=self.object,
            changed_by=self.request.user,
            new_status=self.object.status
        )
        return response

def status_changes_by_date(request, period='day'):
    # Fecha de inicio en la zona horaria local (evita perder cambios de las últimas horas
    # por el desfase UTC: usamos localdate + el lookup __date que compara por día local).
    today = localdate()
    start_date = today.replace(day=1) if period == 'month' else today

    logs = StatusChangeLog.objects.filter(
        timestamp__date__gte=start_date
    ).select_related('lead', 'changed_by').order_by('-timestamp')

    user_type = getattr(request.user.userprofile, 'user_type', '')
    if user_type not in ('admin', 'owner', 'supervisor'):
        logs = logs.filter(changed_by=request.user)

    return render(request, 'lead/status_changes_list.html', {'logs': logs, 'period': period})

class LeadCreateView(LoginRequiredMixin, CreateView):
    model = Lead
    form_class = AddLeadForm
    success_url = reverse_lazy('leads:list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        team = self.request.user.userprofile.active_team
        context['team'] = team
        context['title'] = 'Add lead'

        return context

    def form_valid(self, form):
        team = self.request.user.userprofile.active_team

        self.object = form.save(commit=False)
        self.object.created_by = self.request.user
        self.object.assigned_to = self.request.user
        self.object.team = self.request.user.userprofile.active_team
        self.object.save()

        return redirect(self.get_success_url())



class UploadExcelFileView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        form = UploadExcelFileForm()
        return render(request, 'lead/upload_excel.html', {'form': form})

    def post(self, request, *args, **kwargs):
        form = UploadExcelFileForm(request.POST, request.FILES)

        if form.is_valid():
            cartera = form.cleaned_data['cartera']
            subcartera = cartera.subcartera_default
            excel_file = form.cleaned_data['excel_file']
            wb = load_workbook(excel_file)
            sheet = wb.active
            data = []
            for row in sheet.iter_rows(min_row=2, values_only=True):
                data.append(row)
            for row in data:
                lead = Lead(
                    op=row[0],
                    name=row[1],
                    rut=row[2],
                    dv=row[3],
                    saldo_insoluto=row[4],
                    saldo_deuda=row[5],
                    valor_cuota=row[6],
                    cuotas_atrasadas=row[7],
                    subcartera=subcartera,
                    tipo_cobranza=row[8],
                    status=row[9],
                    ciclo_cartera=row[10],
                    ciclo=row[11],
                    activo=row[12],
                    tiene_aval=row[13],
                    created_by=self.request.user,
                    assigned_to=self.request.user,
                    team=self.request.user.userprofile.active_team,
                )
                lead.save()

            return redirect('leads:list')

        return redirect('leads:list')

class DownloadExcelView(View):
    def get(self, request, *args, **kwargs):
        # Create your Excel file here
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'Clients'

        # Add headers
        headers = ['Op','Name', 'RUT', 'DV', 'Saldo Insoluto', 'Saldo Deuda', 'Valor Cuota', 'Cuotas Atrasadas', 'Cartera', 'Subcartera', 'Tipo Cobranza', 'Status', 'Ciclo Cartera', 'Ciclo', 'Activo', 'Tiene Aval']
        sheet.append(headers)

        # Add data
        for lead in Lead.objects.select_related('subcartera__cartera').all():
            sheet.append([
                lead.op, lead.name, lead.rut, lead.dv, lead.saldo_insoluto, lead.saldo_deuda, lead.valor_cuota, lead.cuotas_atrasadas, lead.subcartera.cartera.nombre, lead.subcartera.nombre, lead.tipo_cobranza, lead.get_status_display(), lead.ciclo_cartera, lead.ciclo, lead.activo, lead.tiene_aval
            ])

        # Save the workbook to a BytesIO stream
        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        # Create the HTTP response
        response = HttpResponse(
            content=output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=clients.xlsx'
        return response

class AddFileView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        pk = kwargs.get('pk')

        form = AddFileForm(request.POST, request.FILES)

        if form.is_valid():
            team = self.request.user.userprofile.active_team
            file = form.save(commit=False)
            file.team = team
            file.lead_id = pk
            file.created_by = request.user
            file.save()

        return redirect('leads:list', pk=pk)

class AddCommentView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        pk = kwargs.get('pk')

        form = AddCommentForm(request.POST)

        if form.is_valid():
            comment = form.save(commit=False)
            comment.team = self.request.user.userprofile.active_team
            comment.created_by = request.user
            comment.lead_id = pk
            comment.save()


        return redirect('leads:detail', pk=pk)

def _puede_ver_lead(user, lead):
    """Un usuario puede ver/anotar un lead si es suyo (asignado/creado) o es supervisor+."""
    profile = getattr(user, 'userprofile', None)
    if profile and profile.user_type in ('admin', 'owner', 'supervisor'):
        return True
    return lead.assigned_to_id == user.pk or lead.created_by_id == user.pk


class ToggleFavoriteView(LoginRequiredMixin, View):
    """Marca/desmarca un lead como favorito del usuario (por AJAX, sin recargar)."""

    def post(self, request, *args, **kwargs):
        lead = get_object_or_404(Lead, pk=kwargs.get('pk'))
        if not _puede_ver_lead(request.user, lead):
            raise PermissionDenied
        if lead.favorited_by.filter(pk=request.user.pk).exists():
            lead.favorited_by.remove(request.user)
            favorited = False
        else:
            lead.favorited_by.add(request.user)
            favorited = True
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'ok': True, 'favorited': favorited})
        return redirect(request.POST.get('next') or reverse('leads:list'))


class AddLeadNoteView(LoginRequiredMixin, View):
    """Crea una nota interna en un lead. Las notas NO entran en los reportes de cartera."""

    def post(self, request, *args, **kwargs):
        lead = get_object_or_404(Lead, pk=kwargs.get('pk'))
        if not _puede_ver_lead(request.user, lead):
            raise PermissionDenied

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        body = (request.POST.get('body') or '').strip()

        if not body:
            if is_ajax:
                return JsonResponse({'ok': False, 'error': 'La nota no puede estar vacía.'}, status=400)
            messages.error(request, 'La nota no puede estar vacía.')
            return redirect(request.POST.get('next') or reverse('leads:detail', kwargs={'pk': lead.pk}))

        note = LeadNote.objects.create(lead=lead, author=request.user, body=body)

        if is_ajax:
            return JsonResponse({
                'ok': True,
                'note': {
                    'author': request.user.username,
                    'created_at': localtime(note.created_at).strftime('%d-%m-%Y %H:%M'),
                    'body': note.body,
                },
            })

        messages.success(request, 'Nota agregada.')
        return redirect(request.POST.get('next') or reverse('leads:detail', kwargs={'pk': lead.pk}))


class AssignLeadsView(LoginRequiredMixin, View):
    template_name = "lead/leads_assign.html"

    def get(self, request, *args, **kwargs):
        if not hasattr(request.user, 'userprofile') or request.user.userprofile.user_type != 'supervisor':
            raise PermissionDenied

        team = request.user.userprofile.active_team
        form = AssignLeadsForm(team=team)
        upload_form = UploadAssignmentFileForm()
        return render(request, self.template_name, {'form': form, 'upload_form': upload_form})

    def post(self, request, *args, **kwargs):
        if not hasattr(request.user, 'userprofile') or request.user.userprofile.user_type != 'supervisor':
            raise PermissionDenied

        team = request.user.userprofile.active_team
        form = AssignLeadsForm(request.POST, team=team)
        upload_form = UploadAssignmentFileForm(request.POST, request.FILES)

        if form.is_valid():
            collector = form.cleaned_data['collector']
            leads = form.cleaned_data['leads']

            for lead in leads:
                lead.assigned_to = collector
                lead.save()
                LeadAssignment.objects.create(
                    lead=lead,
                    user=collector,
                    assigned_by=request.user
                )

            messages.success(request, 'Leads assigned successfully')
            return redirect('leads:list')

        if upload_form.is_valid():
            excel_file = upload_form.cleaned_data['file']
            workbook = openpyxl.load_workbook(excel_file)
            sheet = workbook.active
            data = []

            for row in sheet.iter_rows(min_row=2, values_only=True):
                cartera_nombre = str(row[0]).strip() if row[0] is not None else ''
                subcartera_nombre = str(row[1]).strip() if row[1] is not None else ''
                op = str(row[2]).strip() if row[2] is not None else ''
                collector_username = str(row[3]).strip() if row[3] is not None else ''
                try:
                    cartera = Cartera.objects.get(nombre__iexact=cartera_nombre)
                except Cartera.DoesNotExist:
                    messages.error(request, f'Cartera no encontrada: {cartera_nombre}.')
                    continue

                subcartera = Subcartera.objects.filter(cartera=cartera, nombre__iexact=subcartera_nombre).first()
                if subcartera is None:
                    subcartera = Subcartera.objects.create(cartera=cartera, nombre=subcartera_nombre)

                try:
                    lead = Lead.objects.get(op__iexact=op, subcartera__cartera=cartera, team=team)
                    collector = User.objects.get(username__iexact=collector_username, userprofile__active_team=team)
                    lead.subcartera = subcartera
                    lead.assigned_to = collector
                    lead.save()
                    LeadAssignment.objects.create(
                        lead=lead,
                        user=collector,
                        assigned_by=request.user
                    )
                except Lead.DoesNotExist:
                    messages.error(request, f'Lead not found for OP: {op}, Cartera: {cartera_nombre}.')
                except User.DoesNotExist:
                    messages.error(request, f'Collector with username {collector_username} does not exist.')

            messages.success(request, 'Leads assigned from file successfully')
            return redirect('leads:list')

        return render(request, self.template_name, {'form': form, 'upload_form': upload_form})