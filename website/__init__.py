import os
import threading
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from gmail_reply_reader import start_reply_reader

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)

def init_app(debug: bool | None):
    load_dotenv()
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    app.config['SECRET_KEY'] = "smartshop"
    app.config['SQLALCHEMY_DATABASE_URI'] = "mysql+pymysql://%s:%s@localhost/smartshop" % (db_user, db_password)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    from website.routes import admin, auth
    app.register_blueprint(admin)
    app.register_blueprint(auth)
    # WARNING: Upon adding a new model inside the model class, you should reflect on
    # the addition here as well.
    from website.models import Customer
    with app.app_context():
        db.create_all()

    # Start the Gmail reply reader once.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(
            target=start_reply_reader,
            daemon=True
        ).start()

    app.run(debug=debug)
