import sys
import os
from setuptools import setup, find_packages

if sys.version_info < (3, 6):
    raise Exception(
        "Python 3.6 or higher is required. Your version is %s." % sys.version)

version_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'efb_session_reminder/__version__.py')

__version__ = ""
exec(open(version_path).read())

long_description = open('README.md', encoding="utf-8").read()

setup(
    name='efb-session-reminder-middleware',
    packages=find_packages(
        exclude=["*.tests", "*.tests.*", "tests.*", "tests"]),
    version=__version__,
    description='A middleware for EFB that reminds users before WeChat session expires',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Your Name',
    author_email='your.email@example.com',
    url='https://github.com/yourusername/efb-session-reminder-middleware',
    license='GPLv3',
    include_package_data=True,
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
        "Topic :: Communications :: Chat",
        "Topic :: Utilities"
    ],
    install_requires=[
        "ehforwarderbot>=2.0.0",
        "ruamel.yaml",
    ],
    entry_points={
        "ehforwarderbot.middleware": "efb_session_reminder = efb_session_reminder:SessionReminderMiddleware"
    }
)
