# Siembra definitiva de la config demografica de los resultados, con las decisiones que el
# usuario reviso en el Excel (blacklist para "no corresponde/invalido", no existe para rebote de
# correo, fuera de servicio, y sin accion para rebote de sms/carta/ivr/whatsapp; whatsapp se
# apaga aparte). Reescribe efecto_demografia y desactiva_whatsapp de TODOS los resultados para
# quedar autoritativa (corrige la siembra parcial de 0019). Las reglas viven en
# actions/demografia_rules.py y se replican aca porque las migraciones deben ser autocontenidas.
import unicodedata

from django.db import migrations


def _norm(nombre):
    s = str(nombre or '').strip().upper()
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _efecto(nombre):
    E = _norm(nombre)
    if 'DIRECCION' in E:
        return ''
    if 'NO CORRESPONDE' in E or 'EQUIVOCAD' in E or ('INVALIDO' in E and ('EMAIL' in E or 'CORREO' in E)):
        return 'blacklist'
    if 'FUERA DE SERVICIO' in E or 'NO DISPONIBLE' in E:
        return 'fuera_servicio'
    if 'EMAIL' in E and 'NO ENTREGADO' in E:
        return 'no_existe'
    return ''


def _apaga_wa(nombre):
    E = _norm(nombre)
    return 'SIN WHATSAPP' in E or ('WHATSAPP' in E and 'NO ENTREGADO' in E)


def seed(apps, schema_editor):
    Resultado = apps.get_model('actions', 'Resultado')
    for r in Resultado.objects.all():
        efecto = _efecto(r.nombre)
        wa = _apaga_wa(r.nombre)
        if r.efecto_demografia != efecto or r.desactiva_whatsapp != wa:
            r.efecto_demografia = efecto
            r.desactiva_whatsapp = wa
            r.save(update_fields=['efecto_demografia', 'desactiva_whatsapp'])


class Migration(migrations.Migration):

    dependencies = [
        ('actions', '0019_seed_efecto_demografia'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
