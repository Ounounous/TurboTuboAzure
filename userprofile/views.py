from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth.models import User

from .forms import SignupForm, ProfileDataForm
from .models import Userprofile

from team.models import Team
from lead.models import Lead

def get_userprofile(user):
    userprofile, created = Userprofile.objects.get_or_create(user=user)
    return userprofile

def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)

        if form.is_valid():
            user = form.save()

            team = Team.objects.create(name='The team name', created_by=user)
            team.members.add(user)

            # El signal post_save de User (ver create_user_profile abajo) ya crea el
            # Userprofile en cuanto se guarda el user -- Userprofile.objects.create() acá
            # chocaba con ese y tiraba ValueError en todo signup ("ya existe para este user").
            userprofile = get_userprofile(user)
            userprofile.active_team = team
            userprofile.save(update_fields=['active_team'])

            return redirect('/log-in/')
    else:
        form = SignupForm()

    return render(request, 'userprofile/signup.html', {
        'form': form

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