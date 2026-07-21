from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from userprofile.models import Userprofile


class CrearUsuarioForm(UserCreationForm):
    """Un admin/owner crea un usuario nuevo DENTRO de su propio equipo (a diferencia del
    registro público en /sign-up/, que crea un equipo nuevo por cada persona)."""
    user_type = forms.ChoiceField(choices=Userprofile.USER_TYPES, initial='collector', label='Rol')

    class Meta:
        model = User
        fields = ['username', 'email', 'user_type', 'password1', 'password2']

    email = forms.EmailField(required=False, label='Correo')
