from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from team.models import Team


def _pbx_fernet():
    if not settings.PBX_ENCRYPTION_KEY:
        raise ValueError("PBX_ENCRYPTION_KEY is not set in the environment.")
    return Fernet(settings.PBX_ENCRYPTION_KEY.encode())


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
    # RUT sin guion, sin puntos y sin digito verificador -- algunos reportes de cartera (ej.
    # Tanner) exigen el RUT del ejecutivo que hizo la gestion.
    rut = models.CharField(max_length=15, blank=True)
    # Datos de contacto del cobrador (editables por supervisor/admin desde Configuracion ->
    # Usuarios). El correo del cobrador vive en User.email; aca solo el telefono.
    telefono = models.CharField(max_length=30, blank=True)

    # Credenciales del usuario en la central telefonica (pbxip.cl), usadas para originar
    # llamadas y descargar grabaciones a nombre de este usuario.
    pbx_email = models.CharField(max_length=255, blank=True)
    pbx_password_encrypted = models.CharField(max_length=500, blank=True)
    pbx_extension = models.CharField(max_length=20, blank=True)

    # True cuando un admin creo el usuario con una clave TEMPORAL: en su primer ingreso, el
    # middleware ForcePasswordChange lo obliga a definir una clave propia antes de usar la app.
    # Se apaga solo al cambiarla (userprofile.views.cambiar_password).
    must_change_password = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.get_user_type_display()}"

    def save(self, *args, **kwargs):
        if self.pk is None and Userprofile.objects.filter(user=self.user).exists():
            raise ValueError("Userprofile instance already exists for this user")
        super().save(*args, **kwargs)

    @property
    def pbx_password(self):
        if not self.pbx_password_encrypted:
            return ''
        try:
            return _pbx_fernet().decrypt(self.pbx_password_encrypted.encode()).decode()
        except InvalidToken:
            return ''

    @pbx_password.setter
    def pbx_password(self, raw_password):
        self.pbx_password_encrypted = (
            _pbx_fernet().encrypt(raw_password.encode()).decode() if raw_password else ''
        )

    @property
    def has_pbx_credentials(self):
        return bool(self.pbx_email and self.pbx_password_encrypted and self.pbx_extension)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        userprofile = Userprofile.objects.create(user=instance)
        active_team = Team.objects.filter(members=instance).first()
        if active_team:
            userprofile.active_team = active_team
            userprofile.save()
