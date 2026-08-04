import os
from pathlib import Path

from caselens.api import create_app_from_factory
from caselens.demo import create_demo_application

database_path = Path(os.getenv("CASELENS_DB_PATH", "caselens-demo.db"))
app = create_app_from_factory(lambda: create_demo_application(database_path))
