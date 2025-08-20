import sys
sys.stderr.write(f"WSGI USING: {sys.executable}\n")

from app import app as application
