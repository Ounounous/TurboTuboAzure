class ApexToWwwRedirectMiddleware:
    """
    301 de turbotubo.com hacia www.turbotubo.com. El apex esta en Azure DNS con un registro A a
    la IP compartida/SNI del App Service (Azure no ofrece Alias Record hacia App Service en esta
    suscripcion), asi que no es el dominio canonico -- solo redirige. www si tiene CNAME estable
    hacia el hostname del App Service. Va primero en MIDDLEWARE para no tocar sesion/CSRF/DB en
    una request que de todos modos se va a redirigir.
    """
    APEX_HOST = 'turbotubo.com'
    WWW_HOST = 'www.turbotubo.com'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        if host == self.APEX_HOST:
            from django.http import HttpResponsePermanentRedirect
            return HttpResponsePermanentRedirect(f'https://{self.WWW_HOST}{request.get_full_path()}')
        return self.get_response(request)


class NoStoreAuthenticatedMiddleware:
    """
    Evita que el navegador cachee las PAGINAS (HTML) de un usuario autenticado. Sin esto, tras
    cerrar sesion el boton Atras de Chrome/Firefox muestra la pagina cacheada -- con nombre, RUT
    y deuda del cliente -- sin volver a pedir login (fuga de datos personales, Ley 21.719).

    Se aplica SOLO a respuestas text/html: los estaticos (text/css, JS, imagenes) conservan su
    Cache-Control de larga duracion, asi el navegador no re-descarga el CSS en cada pagina (clave
    para el ancho de banda del usuario). Las descargas (Excel/ZIP, Content-Disposition: attachment)
    tampoco son HTML, y ademas no se muestran con el boton Atras.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            content_type = response.headers.get('Content-Type', '')
            if content_type.startswith('text/html'):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
                response.headers['Pragma'] = 'no-cache'
        return response
