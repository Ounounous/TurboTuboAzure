from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect

from lead.permissions import es_admin_owner

from .forms import TeamForm
from .models import Team

SUPERVISOR_TYPES = ('admin', 'owner', 'supervisor')


@login_required
def teams_list(request):
    # admin/owner ven TODOS los equipos (mismo criterio que Usuarios y Permisos, que ya
    # muestra a todo el mundo sin acotar por equipo); el resto solo los suyos.
    if es_admin_owner(request.user):
        teams = Team.objects.all().order_by('name')
    else:
        teams = Team.objects.filter(members__in=[request.user]).order_by('name')

    teams_data = []
    for team in teams:
        miembros = list(team.members.select_related('userprofile').order_by('username'))
        supervisores = [m for m in miembros if getattr(m, 'userprofile', None) and m.userprofile.user_type in SUPERVISOR_TYPES]
        cobradores = [m for m in miembros if getattr(m, 'userprofile', None) and m.userprofile.user_type == 'collector']
        teams_data.append({'team': team, 'supervisores': supervisores, 'cobradores': cobradores})

    return render(request, 'team/teams_list.html', {
        'teams_data': teams_data,
        'active_team': request.user.userprofile.active_team,
        'crear_equipo_form': TeamForm(),
    })


# A donde volver tras crear un equipo -- whitelist explicita para no armar un open-redirect con
# un valor de POST arbitrario. Se llama tanto desde "Mis equipos" como desde Configuracion.
CREAR_EQUIPO_NEXT = {'team:list', 'configuracion:equipo'}


@login_required
def crear_equipo(request):
    next_name = request.POST.get('next')
    next_name = next_name if next_name in CREAR_EQUIPO_NEXT else 'team:list'

    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save(commit=False)
            team.created_by = request.user
            team.save()
            team.members.add(request.user)

            userprofile = request.user.userprofile
            userprofile.active_team = team
            userprofile.save(update_fields=['active_team'])

            messages.success(request, f'Equipo "{team.name}" creado y activado.')
        else:
            messages.error(request, 'Nombre de equipo inválido.')

    return redirect(next_name)

@login_required
def teams_activate(request, pk):
    if es_admin_owner(request.user):
        # admin/owner puede activar cualquier equipo (los ve todos en la lista); si no era
        # miembro todavia, queda agregado -- no tiene sentido "activar" un equipo del que no
        # formas parte.
        team = get_object_or_404(Team, pk=pk)
        if not team.members.filter(pk=request.user.pk).exists():
            team.members.add(request.user)
    else:
        team = get_object_or_404(Team, members__in=[request.user], pk=pk)

    userprofile = request.user.userprofile
    userprofile.active_team = team
    userprofile.save()

    return redirect('team:detail', pk=pk)

@login_required
def detail(request, pk):
    if es_admin_owner(request.user):
        team = get_object_or_404(Team, pk=pk)
    else:
        team = get_object_or_404(Team, members__in=[request.user], pk=pk)

    return render(request, 'team/detail.html', { 'team': team })

@login_required
def edit_team(request, pk):
    team = get_object_or_404(Team, created_by=request.user, pk=pk)
    
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)

        if form.is_valid():
            form.save()

            messages.success(request, 'Cambios Guardados')

            return redirect('userprofile:myaccount')
    else:
        form = TeamForm(instance=team)

    return render(request, 'team/edit_team.html', {
        'team': team,
        'form': form
    })

