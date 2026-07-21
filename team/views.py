from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect

from .forms import TeamForm
from .models import Team

@login_required
def teams_list(request):
    teams = Team.objects.filter(members__in=[request.user])

    return render(request, 'team/teams_list.html', {
        'teams': teams,
        'active_team': request.user.userprofile.active_team,
        'crear_equipo_form': TeamForm(),
    })


@login_required
def crear_equipo(request):
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

    return redirect('team:list')

@login_required
def teams_activate(request, pk):
    team = get_object_or_404(Team, members__in=[request.user], pk=pk)
    userprofile = request.user.userprofile
    userprofile.active_team = team
    userprofile.save()

    return redirect('team:detail', pk=pk)

@login_required
def detail(request, pk):
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

