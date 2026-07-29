from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Si el usuario tiene must_change_password (clave temporal puesta por un admin), lo redirige
    a definir una clave nueva antes de dejarlo usar cualquier otra pantalla. Se dejan pasar solo:
    la propia pagina de cambio de clave, el logout, el health check y los estaticos/media."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            profile = getattr(user, 'userprofile', None)
            if profile is not None and profile.must_change_password:
                permitido = (
                    request.path.startswith('/media/')
                    or request.path.startswith('/static/')
                    or request.path in (
                        reverse('userprofile:cambiar_password'),
                        '/log-out/',
                        '/health/',
                    )
                )
                if not permitido:
                    return redirect('userprofile:cambiar_password')
        return self.get_response(request)
