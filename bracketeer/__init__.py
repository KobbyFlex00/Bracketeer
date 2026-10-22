import os

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_overrides: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_path=os.path.abspath("instance"))
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY must be set when BRACKETEER_ENV=production")

    # Render terminates TLS at its proxy; trust its forwarded headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    csrf.init_app(app)

    from . import models  # noqa: F401  (register models with SQLAlchemy)
    from .admin.routes import bp as admin_bp
    from .auth import bp as auth_bp
    from .cli import register_cli
    from .public.routes import bp as public_bp
    from .sports import SPORTS
    from .views import register_template_helpers

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    register_cli(app)
    register_template_helpers(app, SPORTS)
    return app
