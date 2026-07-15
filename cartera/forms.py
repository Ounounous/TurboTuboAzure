from django import forms

from .models import Cartera, Subcartera


class CarteraForm(forms.ModelForm):
    class Meta:
        model = Cartera
        fields = ('nombre',)


class SubcarteraForm(forms.ModelForm):
    class Meta:
        model = Subcartera
        fields = ('nombre',)
