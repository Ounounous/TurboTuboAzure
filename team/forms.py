from django import forms

from .models import Team

class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ('name',)
        labels = {'name': 'Nombre del equipo'}