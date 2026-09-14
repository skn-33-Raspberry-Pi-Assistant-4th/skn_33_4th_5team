"""PiCare Django project configuration."""

# PyMySQL is a pure-Python MySQL driver and exposes Django's expected MySQLdb API.
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    # SQLite-only tests can run before optional MySQL dependencies are installed.
    pass
