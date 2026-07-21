from django import forms
from django.contrib.auth.models import User
from cartera.models import Cartera
from .models import Lead, LeadFile

class AddLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ('op', 'name', 'rut', 'dv', 'saldo_insoluto', 'saldo_deuda', 'valor_cuota', 'cuotas_atrasadas', 'subcartera', 'tipo_cobranza', 'status', 'ciclo_cartera', 'ciclo', 'activo', 'tiene_aval',)


class AddFileForm(forms.ModelForm):
    class Meta:
        model = LeadFile
        fields = ('file',)

class UploadExcelFileForm(forms.Form):
    cartera = forms.ModelChoiceField(queryset=Cartera.objects.filter(activo=True), label='Cartera')
    excel_file = forms.FileField(label='Upload Excel file')

class AssignLeadsForm(forms.Form):
    collector = forms.ModelChoiceField(queryset=User.objects.none())
    leads = forms.ModelMultipleChoiceField(queryset=Lead.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if team:
            # Cobradores del mismo equipo unicamente -- un supervisor no puede asignar leads a
            # un cobrador de otro equipo (tenant), sea cual sea su cartera.
            self.fields['collector'].queryset = User.objects.filter(
                userprofile__user_type='collector', userprofile__active_team=team
            )
        base = Lead.objects.filter(team=team) if team else Lead.objects.none()
        if user is not None:
            from .permissions import leads_visibles
            base = leads_visibles(user, base=base)
        self.fields['leads'].queryset = base


class UploadAssignmentFileForm(forms.Form):
    file = forms.FileField(label='Upload Assignment Excel file')