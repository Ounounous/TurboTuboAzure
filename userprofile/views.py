from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import render, redirect

from .forms import ProfileDataForm
from .models import Userprofile

from lead.models import Lead

def get_userprofile(user):
    userprofile, created = Userprofile.objects.get_or_create(user=user)
    return userprofile


@login_required
def cambiar_password(request):
    """Define una clave nueva. Obligatorio en el primer ingreso cuando el admin creo el usuario
    con una clave temporal (must_change_password) -- el middleware ForcePasswordChange redirige
    aca hasta que se cambie. Tambien accesible a voluntad desde Mi cuenta."""
    userprofile = get_userprofile(request.user)
    if request.method == 'POST':
        form = SetPasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            userprofile.must_change_password = False
            userprofile.save(update_fields=['must_change_password'])
            # Sin esto, cambiar la clave cierra la sesion (el hash de sesion cambia).
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Contraseña actualizada.')
            return redirect('dashboard:index')
    else:
        form = SetPasswordForm(user=request.user)
    return render(request, 'userprofile/cambiar_password.html', {
        'form': form, 'obligatorio': userprofile.must_change_password,
    })

@login_required
def myaccount(request):
    user = request.user
    userprofile = get_userprofile(user)
    leads = Lead.objects.filter(assigned_to=user)

    # Las credenciales de la central (SIP/PBX) ya NO se editan aca: las configura un supervisor o
    # admin desde Configuracion -> Usuarios. Aca solo quedan los datos personales (RUT).
    if request.method == 'POST' and request.POST.get('form') == 'profile_data':
        profile_form = ProfileDataForm(request.POST, userprofile=userprofile)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, 'Datos personales guardados.')
            return redirect('userprofile:myaccount')
    else:
        profile_form = ProfileDataForm(userprofile=userprofile)

    return render(request, 'userprofile/myaccount.html', {
        'userprofile': userprofile,
        'leads': leads,
        'profile_form': profile_form,
    })