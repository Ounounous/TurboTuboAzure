from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User

from .models import Userprofile

INPUT_CLASS = 'w-full my-4 py-4 px-6 rounded-xl bg-gray-100'

class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Your username',
        'class': INPUT_CLASS
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Your password',
        'class': INPUT_CLASS
    }))

class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
    
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Your username',
        'class': INPUT_CLASS
    }))
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'placeholder': 'Your email',
        'class': INPUT_CLASS
    }))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Your password',
        'class': INPUT_CLASS
    }))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Repeat your password',
        'class': INPUT_CLASS
    }))


class ProfileDataForm(forms.Form):
    rut = forms.CharField(
        label='RUT (sin puntos, sin guión, SIN dígito verificador)', required=False,
        help_text='Lo exigen algunos reportes de cartera para identificar al ejecutivo (ej. Tanner, columna "Ejecutivo").'
    )

    def __init__(self, *args, **kwargs):
        self.userprofile = kwargs.pop('userprofile')
        super().__init__(*args, **kwargs)
        self.fields['rut'].initial = self.userprofile.rut

    def save(self):
        self.userprofile.rut = self.cleaned_data['rut']
        self.userprofile.save()
        return self.userprofile


class PbxCredentialsForm(forms.Form):
    pbx_email = forms.CharField(label='Usuario/email en pbxip.cl', required=True)
    pbx_password = forms.CharField(
        label='Contraseña en pbxip.cl', required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Déjala en blanco para mantener la que ya está guardada.'
    )
    pbx_extension = forms.CharField(label='Anexo/extensión', required=True)

    def __init__(self, *args, **kwargs):
        self.userprofile = kwargs.pop('userprofile')
        super().__init__(*args, **kwargs)
        self.fields['pbx_email'].initial = self.userprofile.pbx_email
        self.fields['pbx_extension'].initial = self.userprofile.pbx_extension

    def save(self):
        self.userprofile.pbx_email = self.cleaned_data['pbx_email']
        self.userprofile.pbx_extension = self.cleaned_data['pbx_extension']
        if self.cleaned_data['pbx_password']:
            self.userprofile.pbx_password = self.cleaned_data['pbx_password']
        self.userprofile.save()
        return self.userprofile