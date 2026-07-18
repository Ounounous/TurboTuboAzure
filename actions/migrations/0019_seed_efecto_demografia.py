# Siembra la config demografica de los resultados en los casos SIN ambiguedad (revisados sobre
# los arboles de Galgo, Tanner y Nuevo Capital). Los casos con duda ("FONO/TELEFONO NO
# CORRESPONDE", "EMAIL INVALIDO", los "ENVIO ... NO ENTREGADO" de correo/sms/ivr/carta) quedan
# SIN setear a proposito: se definen en /admin o en una siguiente pasada cuando el usuario
# resuelva blacklist-vs-no-existe / no-existe-vs-fuera-de-servicio en el Excel de revision.
import unicodedata

from django.db import migrations


def norm(s):
    s = str(s or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def seed(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    for r in Resultado.objects.all():
        E = norm(r.nombre)
        cambios = []

        # WhatsApp: "SIN WHATSAPP" o "ENVIO WHATSAPP NO ENTREGADO" apagan WhatsApp del numero
        # (el numero sigue activo para llamar).
        if 'SIN WHATSAPP' in E or ('WHATSAPP' in E and 'NO ENTREGADO' in E):
            if not r.desactiva_whatsapp:
                r.desactiva_whatsapp = True
                cambios.append('desactiva_whatsapp')

        # Estado del dato (solo los inequivocos):
        if 'NO CORRESPONDE A TITULAR' in E or 'EQUIVOCAD' in E:
            efecto = 'blacklist'
        elif 'FUERA DE SERVICIO' in E or 'NO DISPONIBLE' in E:
            efecto = 'fuera_servicio'
        else:
            efecto = ''
        # No tocar los de WhatsApp: su numero NO cambia de estado.
        if efecto and 'WHATSAPP' not in E and not r.efecto_demografia:
            r.efecto_demografia = efecto
            cambios.append('efecto_demografia')

        if cambios:
            r.save(update_fields=cambios)


class Migration(migrations.Migration):

    dependencies = [
        ('actions', '0018_resultado_desactiva_whatsapp_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
