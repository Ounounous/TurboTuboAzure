"""
Unica fuente de verdad para eliminar un usuario (ver configuracion.views.UsuariosPermisosView.post,
accion=eliminar_usuario, solo admin/owner). No hacer user.delete() a mano por fuera de aca.

Todo lo que el usuario dejo atras que sea un registro real (gestiones, grabaciones, pagos,
compromisos, archivos, historial de asignaciones, equipos que creo) esta en SET_NULL a nivel de
modelo -- sobrevive intacto, solo pierde la atribucion. Lo unico que necesita manejo explicito aca
es lo que SI depende del ciclo de vida propio del lead:
  - Los leads que tenia asignados se desasignan de verdad (lead.lifecycle.desasignar), no solo
    queda assigned_to=None por el lado del ORM.
  - Si supervisaba alguna subcartera, quien borra queda como su supervisor hasta que se nombre a
    otro (Configuracion -> Usuarios y permisos -> Subcarteras por supervisor).
"""
from django.db import transaction


def eliminar_usuario(target, deleted_by):
    from cartera.models import Subcartera
    from lead.lifecycle import desasignar
    from lead.models import Lead

    with transaction.atomic():
        for lead in Lead.objects.filter(assigned_to=target):
            desasignar(lead, changed_by=deleted_by)

        for subcartera in Subcartera.objects.filter(supervisores=target):
            subcartera.supervisores.add(deleted_by)

        target.delete()
