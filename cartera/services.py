from django.db import transaction

from lead.models import Lead


def eliminar_cartera(cartera):
    """Borra una cartera completa: sus subcarteras, todos los leads que cuelgan de ellas, y todo
    lo que a su vez cuelga de esos leads (gestiones, pagos, compromisos, demografia, notas,
    archivos, historial de status). Las grabaciones de llamadas (actions.CallRecording) NO se
    borran -- su FK a Lead es SET_NULL (retencion legal de 2 anios independiente del lead/
    cartera), asi que sobreviven huerfanas.

    Orden importa: Lead.subcartera y Action/PaymentCommitment.subcartera son PROTECT, asi que
    hay que borrar los leads (lo que en cascada se lleva sus acciones/pagos/compromisos) antes
    de poder borrar las subcarteras.
    """
    with transaction.atomic():
        Lead.objects.filter(subcartera__cartera=cartera).delete()
        cartera.subcarteras.all().delete()
        cartera.delete()
