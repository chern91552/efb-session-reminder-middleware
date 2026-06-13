import sys
from setuptools import setup, find_packages

if sys.version_info < (3, 6):
    raise Exception(
        "Python 3.6 or higher is required. Your version is %s." % sys.version)

__version__ = "1.4.0"

long_description = open('README.md', encoding="utf-8").read()

setup(
    name='efb-session-reminder-middleware',
    packages=find_packages(
        exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    version=__version__,
    description='A middleware for EFB that reminds users before WeChat session expires',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='chern91552',
    author_email='chern91552@example.com',
    url='https://github.com/chern91552/efb-session-reminder-middleware',
    license='GPLv3',
    python_requires='>=3.6',
    keywords=['ehforwarderbot', 'EH Forwarder Bot', 'EH Forwarder Bot Middleware',
              'WeChat', 'Session', 'Reminder'],
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Communications :: Chat",
        "Topic :: Utilities"
    ],
    install_requires=[
        "ehforwarderbot>=2.0.0",
        "ruamel.yaml",
    ],
    extras_require={
        "qr": ["pyqrcode"],
    },
    entry_points={
        "ehforwarderbot.middleware": "efb_session_reminder = efb_session_reminder:SessionReminderMiddleware"
    }
)
