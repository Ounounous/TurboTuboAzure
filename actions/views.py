from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect,render
from django.urls import reverse
from django.views.generic import CreateView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views import View
from .models import Action
from lead.models import Lead
from team.models import Team
from demographics.models import AvalDemographics, Phone
from .forms import ActionForm, LeadSearchForm, DemographicSelectionForm, ActionForm
import openpyxl
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

        return render(
            request,
            'actions/action_index.html',
            {
                'lead_results': lead_results,
                'aval_results': aval_results,
                'query': query
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
            selected_phone = request.session.get('selected_phone')
            selected_email = request.session.get('selected_email')
            form = ActionForm()
            phone_disabled = bool(selected_phone)  # Flag to indicate if phone is selected
            email_disabled = bool(selected_email)  # Flag to indicate if email is selected
            return render(request, 'actions/multistep_form.html', {
                'lead': lead, 'action_form': form, 'step': step,
                'phone_disabled': phone_disabled, 'email_disabled': email_disabled
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
        elif step == 3:
            selected_phone = request.session.get('selected_phone')
            selected_email = request.session.get('selected_email')

            form = ActionForm(request.POST)

            if form.is_valid():
                action = form.save(commit=False)
                action.lead = lead
                action.user = request.user  # Ensure the user is set

                # Ensure previously collected data is set
                action.phone_id = selected_phone  # ForeignKey to Phone model
                action.email = selected_email if not selected_phone else None  # Only save email if phone is not selected
                action.save()

                logger.debug(f"Action saved: {action}, Lead: {lead}, User: {request.user}")

                # Clear session and redirect
                request.session.pop('selected_lead_id', None)
                request.session.pop('selected_phone', None)
                request.session.pop('selected_email', None)

                return redirect('/dashboard/actions/')
            else:
                logger.debug(f"Invalid form data: {form.errors}")

        lead = get_object_or_404(Lead, id=lead_id)
        return render(request, 'actions/multistep_form.html', {
            'lead': lead,
            'action_form': form,
            'step': step,
            'phone_disabled': bool(request.session.get('selected_phone')),
            'email_disabled': bool(request.session.get('selected_email'))
        })

class ActionDownloadExcelView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        scope = kwargs.get('scope', 'team')

        logger.debug(f"User: {request.user}")
        logger.debug(f"UserProfile: {request.user.userprofile}")
        logger.debug(f"Active Team: {request.user.userprofile.active_team}")

        # Create your Excel file
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = f'{scope.capitalize()} Actions'

        # Add headers
        headers = ['Date', 'Lead', 'Action Type', 'Result', 'Comment', 'User']
        sheet.append(headers)

        # Get the appropriate queryset
        if scope == 'team':
            team = request.user.userprofile.active_team
            actions = Action.objects.filter(team=team)
        elif scope == 'user':
            actions = Action.objects.filter(user=request.user)
        else:
            return HttpResponse("Invalid scope")

        logger.debug(f"Number of actions: {actions.count()}")

        # Add data
        for action in actions:
            sheet.append([
                action.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                action.lead.op if action.lead else 'N/A',
                action.get_action_type_display(),
                action.get_result_display(),
                action.comment,
                action.user.username if action.user else 'N/A'
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
        response['Content-Disposition'] = f'attachment; filename={scope}_actions.xlsx'
        return response
