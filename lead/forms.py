from django import forms
from django.contrib.auth.models import User
from cartera.models import Cartera, Subcartera
from .models import Lead, LeadFile

class AddLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ('op', 'name', 'rut', 'dv', 'saldo_insoluto', 'saldo_deuda', 'valor_cuota', 'cuotas_atrasadas', 'subcartera', 'tipo_cobranza', 'status', 'ciclo_cartera', 'ciclo', 'activo', 'tiene_aval',)


class AddFileForm(forms.ModelForm):
    class Meta:
        model = LeadFile
        fields = ('file',)

    def clean_file(self):
        f = self.cleaned_data['file']
        if f and f.size > LeadFile.MAX_BYTES:
            mb = LeadFile.MAX_BYTES // (1024 * 1024)
            raise forms.ValidationError(f'El archivo supera el máximo de {mb} MB.')
        return f

class UploadExcelFileForm(forms.Form):
    cartera = forms.ModelChoiceField(queryset=Cartera.objects.filter(activo=True), label='Cartera')
    excel_file = forms.FileField(label='Upload Excel file')

class QuickAssignForm(forms.Form):
    """Formulario simple para asignar un lead a un cobrador (en la ficha de detalle). No
    obligatorio: dejar la opcion "-- Sin asignar --" desasigna al lead (igual que el boton
    Desasignar de Suspensiones, ver LeadDetailView.post)."""
    collector = forms.ModelChoiceField(
        queryset=User.objects.none(), label='Asignar a', required=False, empty_label='-- Sin asignar --',
    )

    def __init__(self, *args, **kwargs):
        team = kwargs.pop('team', None)
        super().__init__(*args, **kwargs)
        if team:
            self.fields['collector'].queryset = User.objects.filter(
                userprofile__user_type='collector', userprofile__active_team=team
            )


class UploadAssignmentFileForm(forms.Form):
    file = forms.FileField(label='Upload Assignment Excel file')


class MoverSubcarteraForm(forms.Form):
    """Mover un lead a otra subcartera de la MISMA cartera (en la ficha de detalle). El arbol de
    gestion (medios/resultados) es por Cartera, no por Subcartera, asi que este movimiento nunca
    lo cambia -- cruzar de Cartera es otro problema, este form no lo permite."""
    subcartera = forms.ModelChoiceField(
        queryset=Subcartera.objects.none(), label='Mover a',
    )

    def __init__(self, *args, **kwargs):
        cartera = kwargs.pop('cartera', None)
        super().__init__(*args, **kwargs)
        if cartera:
            self.fields['subcartera'].queryset = Subcartera.objects.filter(cartera=cartera).order_by('nombre')


class UploadMoverSubcarteraFileForm(forms.Form):
    file = forms.FileField(label='Excel de mover subcartera')