from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from lead.models import Lead

@login_required
def dashboard(request):
    team = request.user.userprofile.active_team

    leads = Lead.objects.filter(team=team).order_by('-created_at')[0:5]

    return render(request, 'dashboard/dashboard.html', {
        'leads': leads,
    })
