import sys
sys.stderr.write(f"WSGI USING: {sys.executable}\n"); sys.stderr.flush()

from app import app as application
