"""Saved BLE sensors and the last independently received sensor readings."""
from smartshop.extensions import db


class BLESensor(db.Model):
    address = db.Column(db.String(17), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    measurements = db.Column(db.JSON, nullable=False, default=dict)
    last_seen = db.Column(db.String(40))
    rssi = db.Column(db.Integer)
