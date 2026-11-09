"""Profil browser uji: WebKit dengan sentuhan iPhone, tanpa fallback mesin."""
import os


def mesin(pw, nama=None):
    nama = nama or os.getenv('UJI_BROWSER', 'chromium')
    if nama not in ('chromium', 'webkit', 'firefox'):
        raise ValueError('Mesin browser uji tidak dikenal: '+nama)
    return getattr(pw, nama)


def konteks(pw, width=390, height=920):
    options = {}
    if os.getenv('UJI_IPHONE') == '1' and width <= 430:
        options.update(pw.devices['iPhone 13'])
        options.pop('default_browser_type', None)
    options.update(viewport={'width':width,'height':height}, reduced_motion='reduce')
    return options
