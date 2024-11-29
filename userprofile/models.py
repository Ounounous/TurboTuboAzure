from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from team.models import Team


class Userprofile(models.Model):
    USER_TYPES = (
        ('admin', 'Admin'),
        ('owner', 'Owner'),
        ('supervisor', 'Supervisor'),
        ('collector', 'Collector'),
    )

    user = models.OneToOneField(User, related_name='userprofile', on_delete=models.CASCADE)
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='collector')
    active_team = models.ForeignKey(Team, related_name='userprofiles', on_delete=models.CASCADE, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.get_user_type_display()}"

    def save(self, *args, **kwargs):
        if self.pk is None and Userprofile.objects.filter(user=self.user).exists():
            raise ValueError("Userprofile instance already exists for this user")
        super().save(*args, **kwargs)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        userprofile = Userprofile.objects.create(user=instance)
        active_team = Team.objects.filter(members=instance).first()
        if active_team:
            userprofile.active_team = active_team
            userprofile.save()