from django.contrib.auth.models import User
from django.db import models


class Plan(models.Model):
    name = models.CharField(max_length=50)
    price = models.IntegerField()
    description = models.TextField(blank=True, null=True)
    max_leads = models.IntegerField()
    max_clients = models.IntegerField()

    def __str__(self):
        return self.name


class Team(models.Model):
    plan = models.ForeignKey(Plan, related_name='teams', blank=True, null=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    members = models.ManyToManyField(User, related_name='teams')
    # SET_NULL (no CASCADE): borrar a quien creo el equipo NO debe borrar el equipo entero --
    # eso arrastraria en cascada TODOS sus leads (Lead.team es CASCADE) y sus archivos.
    created_by = models.ForeignKey(
        User, related_name='created_teams', on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name