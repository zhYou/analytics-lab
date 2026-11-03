# Superset 6.1 MySQL type inspection imports MySQLdb even for a PyMySQL URI.
# PyMySQL provides the compatible constants and DB-API interface.
import pymysql
pymysql.install_as_MySQLdb()

import os

SECRET_KEY = os.environ['SUPERSET_SECRET_KEY']
SQLALCHEMY_DATABASE_URI = os.environ['SUPERSET_METADATA_URI']
WTF_CSRF_ENABLED = True
ENABLE_PROXY_FIX = True
SUPERSET_WEBSERVER_TIMEOUT = 120
ROW_LIMIT = 10000
SQL_MAX_ROW = 100000
TALISMAN_ENABLED = False  # This preview is loopback-only HTTP.
FEATURE_FLAGS = {'DASHBOARD_CROSS_FILTERS': True}
CACHE_CONFIG = {'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 60}
DATA_CACHE_CONFIG = {'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 60}
LANGUAGES = {'en': {'flag': 'us', 'name': 'English'}, 'zh': {'flag': 'cn', 'name': '中文'}}
