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
    search = forms.CharField(
        required=False,
        label='Buscar clientes',
        widget=forms.TextInput(attrs={'placeholder': 'Buscar por OP, RUT o nombre...', 'class': 'form-control'})
    )
    collector = forms.ModelChoiceField(queryset=User.objects.none(), label='Cobrador')
    leads = forms.ModelMultipleChoiceField(queryset=Lead.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if team:
            # Cobradores del mismo equipo unicamente
            self.fields['collector'].queryset = User.objects.filter(
                userprofile__user_type='collector', userprofile__active_team=team
            )
        base = Lead.objects.filter(team=team) if team else Lead.objects.none()
        if user is not None:
            from .permissions import leads_visibles
            base = leads_visibles(user, base=base)
        self.fields['leads'].queryset = base

    def clean(self):
        cleaned_data = super().clean()
        collector = cleaned_data.get('collector')
        leads = cleaned_data.get('leads')
        if not collector:
            self.add_error('collector', 'Debe seleccionar un cobrador')
        if not leads:
            self.add_error('leads', 'Debe seleccionar al menos un cliente')
        return cleaned_data


class QuickAssignForm(forms.Form):
    """Formulario simple para asignar un lead a un cobrador (en la ficha de detalle)."""
    collector = forms.ModelChoiceField(queryset=User.objects.none(), label='Asignar a')

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        super().__init__(*args, **kwargs)
        if team:
            self.fields['collector'].queryset = User.objects.filter(
                userprofile__user_type='collector', userprofile__active_team=team
            )


class UploadAssignmentFileForm(forms.Form):
    file = forms.FileField(label='Upload Assignment Excel file')