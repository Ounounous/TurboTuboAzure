from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse_lazy
from django.http import HttpResponse
from django.views.generic import ListView, DetailView, DeleteView, UpdateView, CreateView, View
from django.utils.timezone import now
from .models import StatusChangeLog, Team
import openpyxl
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

from openpyxl import load_workbook

from .forms import AddCommentForm, AddFileForm, AddLeadForm, UploadExcelFileForm, AssignLeadsForm, UploadAssignmentFileForm
from .models import Lead, LeadAssignment, User
from demographics.models import IDDemographics, AvalDemographics, IDItem, Phone

from client.models import Client, Comment as ClientComment


class LeadListView(LoginRequiredMixin, ListView):
    model = Lead

    def get_queryset(self):
        queryset = super(LeadListView, self).get_queryset()
        return queryset.filter(Q(assigned_to__pk=self.request.user.pk) | Q(created_by=self.request.user))
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['leads'] = self.get_queryset()
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

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        print(obj.__dict__)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['demographics'] = IDDemographics.objects.filter(lead=self.object)
        context['aval_demographics'] = AvalDemographics.objects.filter(
            id_demographics__in=context['demographics']).first()
        context['form'] = AddCommentForm()
        context['fileform'] = AddFileForm()
        context['phones'] = self.object.phone_set.all()
        print(f"Phones for Lead {self.object.pk}: {[phone.phone_number for phone in context['phones']]}")
        for phone in context['phones']:
            print(f"Phone: {phone.phone_number}, Type: {phone.phone_type}, Status: {phone.phone_number_status}")
        print(self.object.__dict__)

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
    # Determine start date for filtering logs
    if period == 'day':
        start_date = now().date()
    elif period == 'month':
        start_date = now().replace(day=1).date()

    user_type = request.user.userprofile.user_type

    # Check the user type and filter logs accordingly
    if user_type in ['admin', 'supervisor']:
        # Admins and supervisors see all logs
        logs = StatusChangeLog.objects.filter(
            timestamp__gte=start_date
        ).order_by('-timestamp')
    else:
        # Other users (collectors, etc.) only see their own logs
        logs = StatusChangeLog.objects.filter(
            timestamp__gte=start_date,
            changed_by=request.user
        ).order_by('-timestamp')

    return render(request, 'lead/status_changes_list.html', {'logs': logs})

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
                    cartera=row[8],
                    tipo_cobranza=row[9],
                    status=row[10],
                    ciclo_cartera=row[11],
                    ciclo=row[12],
                    activo=row[13],
                    tiene_aval=row[14],
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
        headers = ['Op','Name', 'RUT', 'DV', 'Saldo Insoluto', 'Saldo Deuda', 'Valor Cuota', 'Cuotas Atrasadas', 'Cartera', 'Tipo Cobranza', 'Status', 'Ciclo Cartera', 'Ciclo', 'Activo', 'Tiene Aval']
        sheet.append(headers)

        # Add data
        for lead in Lead.objects.all():
            sheet.append([
                lead.op, lead.name, lead.rut, lead.dv, lead.saldo_insoluto, lead.saldo_deuda, lead.valor_cuota, lead.cuotas_atrasadas, lead.cartera, lead.tipo_cobranza, lead.get_status_display(), lead.ciclo_cartera, lead.ciclo, lead.activo, lead.tiene_aval
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

class ConvertToClientView(LoginRequiredMixin, View):
    def get(self, request, *arg, **kwargs):
        pk = self.kwargs.get('pk')
        lead = get_object_or_404(Lead, created_by=request.user, pk=pk)
        team = self.request.user.userprofile.active_team

        client = Client.objects.create(
            name=lead.name,
            email=lead.email,
            description=lead.description,
            created_by=request.user,
            team=team,   
        )

        lead.converted_to_client = True
        lead.save()

        # convert lead comment to client comments #

        comments = lead.comments.all()

        for comment in comments:
            ClientComment.objects.create(
                client = client,
                content = comment.content, 
                created_by = comment.created_by,
                team = team
            )

        # show message and redirect #

        messages.success(request, 'ID convertida')

        return redirect('leads:list')

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
                op = row[0]
                cartera = row[1]
                collector_username = row[2]  # Assuming the username is in the third column
                try:
                    lead = Lead.objects.get(op=op, cartera=cartera, team=team)
                    collector = User.objects.get(username=collector_username, userprofile__active_team=team)
                    lead.assigned_to = collector
                    lead.save()
                    LeadAssignment.objects.create(
                        lead=lead,
                        user=collector,
                        assigned_by=request.user
                    )
                except Lead.DoesNotExist:
                    messages.error(request, f'Lead not found for OP: {op}, Cartera: {cartera}.')
                except User.DoesNotExist:
                    messages.error(request, f'Collector with username {collector_username} does not exist.')

            messages.success(request, 'Leads assigned from file successfully')
            return redirect('leads:list')

        return render(request, self.template_name, {'form': form, 'upload_form': upload_form})