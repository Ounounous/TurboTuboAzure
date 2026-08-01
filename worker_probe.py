"""
Servidor HTTP minimo para el App Service WORKER (ver startup-worker.sh).

Por que existe: Azure App Service exige que TODO contenedor escuche en un puerto HTTP. Si no
detecta ninguno en 230s lo declara fallido y lo mata ("Container did not respond to startup probe
on port 8000... No listening ports were detected"), reiniciandolo en bucle. El worker solo corre
Celery (worker + beat), que no sirve HTTP -- sin esto Azure lo mataba cada ~4 minutos, y las
tareas de fondo quedaban encoladas sin procesarse.

Responde 200 en cualquier ruta con un JSON simple. NO expone datos ni toca la base: es solo la
senal de vida que Azure necesita para dejar corriendo el contenedor.
"""
import http.server
import json
import os
import socketserver

PORT = int(os.environ.get('PORT', '8000'))


class ProbeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = json.dumps({'status': 'ok', 'role': 'celery-worker'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    # La sonda de Azure pega cada pocos segundos: sin esto llena el log de ruido.
    def log_message(self, *args):
        pass


class Server(socketserver.TCPServer):
    allow_reuse_address = True  # evita "Address already in use" al reiniciar el contenedor


if __name__ == '__main__':
    with Server(('0.0.0.0', PORT), ProbeHandler) as httpd:
        httpd.serve_forever()
