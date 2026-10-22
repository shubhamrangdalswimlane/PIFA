# Vercel Python function entry point. vercel.json rewrites /api/* here and
# includes the pifa_api package in the bundle.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pifa_api.main import app  # noqa: E402,F401
