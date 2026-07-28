import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

PBX_BASE_URL = 'https://pbxip.cl/api/v2'


class PbxError(Exception):
    pass


class PbxClient:
    """
    Thin client for the pbxip.cl REST API (JWT auth, per-user credentials).

    Field names / request shapes below were confirmed against a working sibling
    project (zoiper_bot_mudo) that already talks to this same API in production,
    since the public OpenAPI spec didn't document the CDR row schema.
    """

    def __init__(self, email, password, timeout=10):
        self.email = email
        self.password = password
        self.timeout = timeout
        self._token = None

    def _login(self):
        resp = requests.post(
            f'{PBX_BASE_URL}/login',
            data={'email': self.email, 'password': self.password},  # form-data, not JSON
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise PbxError(f'Login failed ({resp.status_code}): {resp.text}')
        data = resp.json()
        token = data.get('access_token') or data.get('token') or data.get('data', {}).get('token')
        if not token:
            raise PbxError(f'Login succeeded but no token found in response: {data}')
        self._token = token
        return self._token

    def _headers(self):
        if not self._token:
            self._login()
        return {'Authorization': f'Bearer {self._token}', 'Content-Type': 'application/json'}

    def _request(self, method, path, retry=True, **kwargs):
        resp = requests.request(method, f'{PBX_BASE_URL}{path}', headers=self._headers(), timeout=self.timeout, **kwargs)
        if resp.status_code == 401 and retry:
            self._token = None
            return self._request(method, path, retry=False, **kwargs)
        if resp.status_code >= 400:
            raise PbxError(f'{method} {path} failed ({resp.status_code}): {resp.text}')
        return resp

    def originate_call(self, extension, destination):
        """Rings `extension` first, then bridges to `destination` once answered."""
        return self._request('POST', '/call', json={
            'extension': int(extension),
            'destination': int(destination),
        })

    def list_cdr(self, month, destination=None, since=None, limit=10):
        """
        List CDR rows for the given month. If `destination` is given, filters
        server-side to outgoing calls to that number (matches zoiper_bot_mudo's
        get_cdr()). `since` narrows the date range (defaults to the whole month).
        """
        params = {'month': month, 'limit': limit, 'order': '-calldate'}
        if destination:
            params['filters[filters][number]'] = int(str(destination).strip())
            params['filters[filters][direction][outgoing]'] = 'true'
        if since:
            since_buffered = since - timedelta(minutes=2)
            params['filters[filters][date][initDate]'] = since_buffered.strftime('%Y-%m-%d')
            params['filters[filters][date][endDate]'] = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')

        data = self._request('GET', '/pbx/loadCdr', params=params).json()
        return data if isinstance(data, list) else data.get('data', [])

    def download_recording(self, month, cdr_id):
        return self._request('GET', f'/pbx/recordFile/{month}/{cdr_id}').content


def get_pbx_master_client():
    """
    Devuelve el cliente de la cuenta MAESTRA (una sola cuenta admin consulta/descarga por todas
    las extensiones), configurada por entorno (PBX_MASTER_EMAIL / PBX_MASTER_PASSWORD). Si no esta
    configurada, devuelve None y el llamador cae al modo por-usuario (credenciales de cada uno).
    """
    from django.conf import settings
    email = getattr(settings, 'PBX_MASTER_EMAIL', '') or ''
    password = getattr(settings, 'PBX_MASTER_PASSWORD', '') or ''
    if email and password:
        return PbxClient(email, password)
    return None
