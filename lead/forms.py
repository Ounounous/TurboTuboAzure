from django import forms
from django.contrib.auth.models import User
from .models import Lead, Comment, LeadFile

class AddLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ('op', 'name', 'rut', 'dv', 'saldo_insoluto', 'saldo_deuda', 'valor_cuota', 'cuotas_atrasadas', 'cartera', 'tipo_cobranza', 'status', 'ciclo_cartera', 'ciclo', 'activo', 'tiene_aval',)


class AddCommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('content',)


class AddFileForm(forms.ModelForm):
    class Meta:
        model = LeadFile
        fields = ('file',)

class UploadExcelFileForm(forms.Form):
    excel_file = forms.FileField(label='Upload Excel file')

class AssignLeadsForm(forms.Form):
    collector = forms.ModelChoiceField(queryset=User.objects.filter(userprofile__user_type='collector'))
    leads = forms.ModelMultipleChoiceField(queryset=Lead.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        super().__init__(*args, **kwargs)
        if team:
            self.fields['leads'].queryset = Lead.objects.filter(team=team)


class UploadAssignmentFileForm(forms.Form):
    file = forms.FileField(label='Upload Assignment Excel file')