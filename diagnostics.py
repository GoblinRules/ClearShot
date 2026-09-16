"""Bounded local diagnostics for windowed builds, which have no stderr."""

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading

_fault_file = None


def configure_diagnostics():
    global _fault_file
    folder = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ClearShot' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / 'clearshot.log', maxBytes=1024 * 1024, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    previous_fault = folder / 'native-crash.log'
    if previous_fault.exists():
        previous_fault.replace(folder / 'native-crash.previous.log')
    _fault_file = previous_fault.open('w', encoding='utf-8')
    faulthandler.enable(file=_fault_file)

    def report_exception(exc_type, exc_value, traceback):
        logging.getLogger('clearshot').critical(
            'Unhandled exception', exc_info=(exc_type, exc_value, traceback)
        )

    sys.excepthook = report_exception
    threading.excepthook = lambda args: report_exception(
        args.exc_type, args.exc_value, args.exc_traceback
    )
    from PyQt6.QtCore import qInstallMessageHandler, QtMsgType

    def qt_message(kind, context, message):
        level = logging.INFO if kind == QtMsgType.QtInfoMsg else logging.WARNING
        logging.getLogger('qt').log(level, message)

    qInstallMessageHandler(qt_message)
    return folder
