"""Validate installable PWA metadata without making any external requests."""
import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from http.server import ThreadingHTTPServer
import threading
from urllib.request import urlopen
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

class TestPWAAssets(TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('pwa_server',ROOT/'server.py')
        cls.app=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.app)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),cls.app.Handler)
        cls.base=f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)
    def get(self,path):
        with urlopen(self.base+path,timeout=4) as response:
            return response.headers, response.read()
    def test_manifest_and_icons(self):
        headers,data=self.get('/manifest.webmanifest')
        self.assertIn('application/manifest+json',headers['Content-Type'])
        manifest=json.loads(data)
        self.assertEqual(manifest['display'],'standalone')
        self.assertEqual(manifest['start_url'],'/')
        self.assertEqual(manifest['theme_color'],'#ffffff')
        for icon in manifest['icons']:
            self.assertTrue(self.get(icon['src'])[0]['Content-Type'].startswith('image/png'))
            image=Image.open(ROOT/'public'/icon['src'].lstrip('/'))
            self.assertEqual(image.size,tuple(map(int,icon['sizes'].split('x'))))
    def test_worker_and_offline_available(self):
        headers,data=self.get('/sw.js')
        self.assertIn('javascript',headers['Content-Type'])
        text=data.decode('utf-8')
        self.assertIn('self.addEventListener(\'fetch\'',text)
        self.assertIn("url.pathname.startsWith('/api/')",text)
        self.assertIn("SHELL_CACHE = 'trackroom-shell-v6.9.2'",text)
        for path, mime in [('/login-prism.webp', 'image/webp'), ('/home.css?v=6.9.2', 'text/css'),
                           ('/home.js?v=6.9.2', 'application/javascript'), ('/fonts/plex-sans.woff2', 'font/woff2'),
                           ('/room-bubbles.js?v=6.9.2', 'application/javascript'), ('/room-bubbles.css?v=6.9.2', 'text/css'),
                           ('/catalog-filters.js?v=6.9.2', 'application/javascript'), ('/catalog-filters.css?v=6.9.2', 'text/css')]:
            self.assertIn(path, text)
            self.assertTrue(self.get(path)[0]['Content-Type'].startswith(mime))
        self.assertIn('인터넷 연결',self.get('/offline.html')[1].decode('utf-8'))
    def test_html_has_install_button_and_meta(self):
        html=self.get('/')[1].decode('utf-8')
        self.assertIn('rel="manifest"',html)
        self.assertIn('id="installAppHome"',html)
        self.assertIn('id="roomMenuInstallApp"',html)
        self.assertIn('id="installHelpOverlay"',html)
        self.assertIn('/app.js?v=6.9.2',html)
        self.assertIn('/room-bubbles.js?v=6.9.2',html)
        self.assertIn('/room-bubbles.css?v=6.9.2',html)
        self.assertIn('/style.css?v=6.9.2',html)
        self.assertIn('/home.js?v=6.9.2',html)
        self.assertIn('/home.css?v=6.9.2',html)
    def test_app_landing_exposes_auth_and_invite_controls(self):
        html=self.get('/')[1].decode('utf-8')
        self.assertNotIn('record-visual',html)
        self.assertIn('id="authOverlay" class="entry-screen"',html)
        self.assertIn('id="authSubmit"',html)
        self.assertIn('id="registerTab"',html)
        self.assertIn('aria-controls="roomAccess" aria-expanded="false"',html)
        self.assertIn('id="createForm"',html)
        self.assertIn('id="joinForm"',html)
        for panel in ('dashboard', 'dashCarousel', 'dashMiniPlayer', 'dashRooms', 'dashSpectrumLine'):
            self.assertIn(f'id="{panel}"', html)
