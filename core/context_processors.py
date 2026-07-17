import os

from django.conf import settings


def asset_version(request):
    """
    Versión de cache-busting para los CSS propios (theme.css/main.min.css). Usa la fecha de
    modificación de theme.css como número de versión: cada vez que se recompila el CSS, el
    navegador ve una URL distinta (?v=...) y descarta el caché viejo automáticamente en vez
    de seguir mostrando estilos desactualizados hasta que alguien haga un hard refresh.
    """
    try:
        path = os.path.join(settings.BASE_DIR, 'static', 'theme.css')
        version = int(os.path.getmtime(path))
    except OSError:
        version = 0
    return {'asset_v': version}
