import os
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)

def init_app(debug: bool | None):
    load_dotenv()
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    app.config['SQLALCHEMY_DATABASE_URI'] = "mysql+pymysql://%s:%s@localhost/smartshop" % (db_user, db_password)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    # WARNING: Upon adding a new model inside the model class, you should reflect on
    # the addition here as well.
    from .models import Customer
    with app.app_context():
        db.create_all()

    from .routes import init_routes
    init_routes()

    app.run(debug=debug)
