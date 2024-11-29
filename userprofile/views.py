from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth.models import User

from .forms import SignupForm
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
            team.save()
            
            Userprofile.objects.create(user=user, active_team=team)

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
    return render(request, 'userprofile/myaccount.html', {
        'userprofile': userprofile,
        'leads': leads
    })