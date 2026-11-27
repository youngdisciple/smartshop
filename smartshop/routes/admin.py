from flask import Blueprint, render_template, request
from smartshop.extensions import db
from smartshop.models import Customer
from smartshop.presentation import report_csv
from smartshop.security import admin_required
from smartshop.services import reports

admin = Blueprint("admin", __name__, url_prefix="/admin")


@admin.route("/")
@admin_required
def index_customer():
    customers = db.session.execute(db.select(Customer).order_by(Customer.name)).scalars().all()
    return render_template("admin/index.html", customers=customers)


@admin.get('/reports')
@admin_required
def report_inventory():
    category = request.args.get('category', '')
    rows = reports.inventory(category)
    if request.args.get('format') == 'csv':
        return report_csv.inventory(rows)
    if request.args.get('fragment') == '1':
        return render_template('reports/inventory_rows.html', rows=rows)
    return render_template('reports/inventory.html', rows=rows, category=category,
                           categories=reports.categories())


@admin.get('/reports/sales')
@admin_required
def report_sales():
    start, end = reports.period()
    category = request.args.get('category', '')
    limit = request.args.get('limit', 3, type=int)
    limit = min(100, max(1, limit))
    rows = reports.product_sales(start, end, category)
    top = rows[:limit]
    bottom = sorted(rows, key=lambda row: (row.quantity, row.name, row.id))[:limit]
    revenue = sum(row.revenue for row in rows)
    units = sum(row.quantity for row in rows)
    if request.args.get('format') == 'csv':
        return report_csv.sales(start, end, rows, top, bottom, revenue, units)
    return render_template('reports/sales.html', start=start, end=end, rows=rows,
                           categories=reports.categories(include_archived=True), category=category,
                           limit=limit, top=top, bottom=bottom, revenue=revenue, units=units)


@admin.get('/reports/activity')
@admin_required
def report_activity():
    start, end = reports.period()
    days, total, new = reports.customer_activity(start, end)
    busiest = max(count for _, count in days)
    quietest = min(count for _, count in days)
    if request.args.get('format') == 'csv':
        return report_csv.activity(start, end, days, total, new, busiest, quietest)
    return render_template('reports/activity.html', start=start, end=end, days=days,
                           total=total, new=new, busiest=busiest, quietest=quietest)
